from pydantic_ai import Agent

agent = Agent('gemini-2.5-pro-preview-03-25')


result = agent.run_sync('Where does "hello world" come from?')  
print(result.output)