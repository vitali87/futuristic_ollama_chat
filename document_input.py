from pydantic_ai import Agent, DocumentUrl
from pydantic import BaseModel, Field

class ExtractedContent(BaseModel):
    DocumentUrlCode: str = Field(description='The code example of the document url input')
    BinaryContentCode: str = Field(description='The code example of the binary content input')

agent = Agent(model='google-gla:gemini-2.5-pro-preview-05-06', output_type=ExtractedContent)
result = agent.run_sync(
    [
        'What is the main content of this document?',
        DocumentUrl(url='https://ai.pydantic.dev/input/#document-input'),
    ]
)
print(result.output)