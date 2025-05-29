from __future__ import annotations as _annotations

import asyncio
import json
import sqlite3
from collections.abc import AsyncIterator
from concurrent.futures.thread import ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import partial
from pathlib import Path
from typing import Annotated, Any, Callable, Literal, TypeVar

import fastapi
# import logfire # Removed logfire
from fastapi import Depends, Request, File, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from typing_extensions import LiteralString, ParamSpec, TypedDict


from pydantic_ai import Agent, BinaryContent
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.messages import (
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    TextPart,
    UserPromptPart,
)

# Configure Ollama model
ollama_model = OpenAIModel(
    model_name='qwen2.5vl:72b-q4_K_M', # Or your preferred Ollama model
    provider=OpenAIProvider(base_url='http://localhost:11434/v1')
)
agent = Agent(ollama_model) # Using Ollama model
THIS_DIR = Path(__file__).parent


@asynccontextmanager
async def lifespan(_app: fastapi.FastAPI) -> AsyncIterator[dict[str, Any]]:
    # Removed 'db': db from yield as Database class will be simplified
    # We might not need the lifespan for db if we simplify it further
    # For now, let's keep it simple and connect directly or remove if unused
    async with Database.connect() as db: # This might change based on Database simplification
        yield {'db': db} # Keep for now, will adjust with Database changes


app = fastapi.FastAPI(lifespan=lifespan)
# logfire.instrument_fastapi(app) # Removed logfire


@app.get('/')
async def index() -> FileResponse:
    return FileResponse((THIS_DIR / 'chat_app.html'), media_type='text/html')


@app.get('/chat_app.ts')
async def main_ts() -> FileResponse:
    return FileResponse((THIS_DIR / 'chat_app.ts'), media_type='text/plain')


async def get_db(request: Request) -> Database:
    return request.state.db


@app.get('/chat/')
async def get_chat(database: Database = Depends(get_db)) -> Response:
    msgs = await database.get_messages()
    return Response(
        b'\n'.join(json.dumps(to_chat_message(m)).encode('utf-8') for m in msgs),
        media_type='text/plain',
    )


@app.delete("/chat/") # New DELETE endpoint
async def delete_chat(database: Database = Depends(get_db)) -> Response:
    await database.clear_messages()
    return Response(status_code=204) # No content, success


class ChatMessage(TypedDict):
    role: Literal['user', 'model']
    timestamp: str
    content: str


def to_chat_message(m: ModelMessage) -> ChatMessage:
    first_part = m.parts[0]
    if isinstance(m, ModelRequest):
        if isinstance(first_part, UserPromptPart):
            user_content_str = ""
            document_attached_note = ""
            if isinstance(first_part.content, str):
                user_content_str = first_part.content
            elif isinstance(first_part.content, list):
                for item in first_part.content:
                    if isinstance(item, str):
                        user_content_str = item # Display the first string found
                        # break # If you only want the very first string part
                    elif isinstance(item, BinaryContent):
                        document_attached_note = " (document attached)"
                if not user_content_str and document_attached_note: # Only doc, no text
                    user_content_str = "[document content]"
            else:
                # Should not happen if user_message_content is properly formed
                raise ValueError("Unexpected UserPromptPart content type")
            
            if not user_content_str: # Fallback if no string content found
                 user_content_str = "[User message - unable to display content]"

            return {
                'role': 'user',
                'timestamp': first_part.timestamp.isoformat(),
                'content': user_content_str + document_attached_note,
            }
    elif isinstance(m, ModelResponse):
        if isinstance(first_part, TextPart):
            return {
                'role': 'model',
                'timestamp': m.timestamp.isoformat(),
                'content': first_part.content,
            }
    raise UnexpectedModelBehavior(f'Unexpected message type for chat app: {m}')


@app.post('/chat/')
async def post_chat(
    prompt: Annotated[str, fastapi.Form()],
    document: Annotated[UploadFile | None, File()] = None,
    database: Database = Depends(get_db),
) -> StreamingResponse:
    # Read document content immediately if present
    doc_bytes_content: bytes | None = None
    doc_media_type_content: str | None = None

    if document:
        try:
            # Read the file content immediately and store it.
            doc_bytes_content = await document.read()
            doc_media_type_content = document.content_type
        except Exception as e:
            print(f"Error reading document upfront: {e}")
            # Decide how to handle this - e.g., send an error message to the user or just log
        finally:
            try:
                await document.close() # Ensure the uploaded file is closed
            except Exception as e_close:
                print(f"Error closing document upfront (might be already closed): {e_close}")

    async def stream_messages() -> AsyncIterator[bytes]:
        user_message_list: list[Any] = [prompt]

        # Use the pre-read document content
        if doc_bytes_content and doc_media_type_content:
            user_message_list.append(
                BinaryContent(data=doc_bytes_content, media_type=doc_media_type_content)
            )
        # else: (handled by the initial check - if they are None, nothing is appended)
            
        # Stream the user prompt for immediate display
        yield (
            json.dumps(
                {
                    'role': 'user',
                    'timestamp': datetime.now(tz=timezone.utc).isoformat(),
                    'content': prompt, 
                }
            ).encode('utf-8')
            + b'\n'
        )
        
        messages = await database.get_messages()
        async with agent.run_stream(user_message_list, message_history=messages) as result:
            async for text_chunk in result.stream(debounce_by=0.01):
                m = ModelResponse(
                    parts=[TextPart(text_chunk)], timestamp=result.timestamp()
                )
                yield json.dumps(to_chat_message(m)).encode('utf-8') + b'\n'

        await database.add_messages(result.new_messages_json())

    return StreamingResponse(stream_messages(), media_type='text/plain')


P = ParamSpec('P')
R = TypeVar('R')


@dataclass
class Database:
    con: sqlite3.Connection
    _loop: asyncio.AbstractEventLoop
    _executor: ThreadPoolExecutor

    @classmethod
    @asynccontextmanager
    async def connect(
        cls, file: Path = Path('chat_ollama.db')
    ) -> AsyncIterator[Database]:
        loop = asyncio.get_running_loop()
        executor = ThreadPoolExecutor()
        con = None  # Initialize con to None
        slf = None # Initialize slf to None
        try:
            con = await loop.run_in_executor(executor, cls._connect, file)
            slf = cls(con, loop, executor)
            yield slf
        finally:
            if slf and slf.con: # Check if slf and slf.con exist
                await slf._asyncify(slf.con.close)
            executor.shutdown(wait=True)

    @staticmethod
    def _connect(file: Path) -> sqlite3.Connection:
        con = sqlite3.connect(str(file))
        # con = logfire.instrument_sqlite3(con) # Removed logfire
        cur = con.cursor()
        cur.execute(
            'CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY AUTOINCREMENT, message_list TEXT);'
        )
        # It's good practice to also allow deleting all messages
        # cur.execute('DELETE FROM messages;') # Example if we wanted to clear on connect, not here
        con.commit()
        return con

    async def add_messages(self, messages_json: bytes) -> None:
        await self._asyncify(
            self._execute,
            'INSERT INTO messages (message_list) VALUES (?);',
            messages_json,
            commit=True,
        )

    async def clear_messages(self) -> None: # New method to clear messages
        await self._asyncify(self._execute, 'DELETE FROM messages;', commit=True)
        # Optionally, for SQLite, you might want to vacuum to reclaim space
        # await self._asyncify(self._execute, 'VACUUM;', commit=True)

    async def get_messages(self) -> list[ModelMessage]:
        c = await self._asyncify(
            self._execute, 'SELECT message_list FROM messages ORDER BY id'
        )
        rows = await self._asyncify(c.fetchall)
        messages: list[ModelMessage] = []
        for row in rows:
            messages.extend(ModelMessagesTypeAdapter.validate_json(row[0]))
        return messages

    def _execute(
        self, sql: LiteralString, *args: Any, commit: bool = False
    ) -> sqlite3.Cursor:
        cur = self.con.cursor()
        cur.execute(sql, args)
        if commit:
            self.con.commit()
        return cur

    async def _asyncify(
        self, func: Callable[P, R], *args: P.args, **kwargs: P.kwargs
    ) -> R:
        return await self._loop.run_in_executor(
            self._executor,
            partial(func, **kwargs),
            *args,
        )


if __name__ == '__main__':
    import uvicorn

    # Ensure the path to app is correct if main.py is in a subdirectory
    # For now, assuming main.py is at the root of where uvicorn runs
    uvicorn.run('main:app', reload=True, reload_dirs=[str(THIS_DIR)]) 