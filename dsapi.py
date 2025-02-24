from openai import OpenAI

#API key 替换为上述模型广场API调用弹窗中查询的API Key
#Base URL 替换为上述模型广场API调用弹窗中查询的调用地址+版本
client = OpenAI(api_key="_yV91xd1MYtZvKbOl2NLWfZh8PR_tJfIBnJ9j7ZZbFQ", base_url="https://zhenze-huhehaote.cmecloud.cn/inference-api/exp-api/inf-1336781912337387520/v1"
) 

response = client.chat.completions.create(
    model="default",
    messages=[
        {"role": "system", "content": "You are a helpful assistant"},
        {"role": "user", "content": "请简单介绍下苏州"},
  ],
    max_tokens=1024,
    temperature=0.6,
    stream=False
)

print(response.choices[0].message.content)