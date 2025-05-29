from pydantic_ai import Agent
from pydantic_ai.common_tools.duckduckgo import duckduckgo_search_tool
from pydantic import BaseModel

class ListMovies(BaseModel):
    movie1: str
    movie2: str
    movie3: str
    movie4: str
    movie5: str

agent = Agent(
    'google-gla:gemini-2.5-pro-preview-05-06',
    tools=[duckduckgo_search_tool()],
    system_prompt='You are outdated and the current year is 2025. Use DuckDuckGo tool to search for the given query and return the results.',
    output_type=ListMovies
)

result = agent.run_sync(
    'List the top 5 highest-grossing animated films so far in 2025? You MUST give TOP 5 results, no excuses. Do a thorogh search if you have to'
)
print(result.output)
