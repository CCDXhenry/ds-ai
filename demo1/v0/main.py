"""
OpenAI玄幻小说冒险生成器
依赖：pip install openai python-dotenv
"""

import os
import sys
import time
from typing import List, Dict
import openai
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")

class StoryManager:
    """管理故事生成状态和上下文"""
    
    def __init__(self):
        self.story_history: List[Dict] = []
        self.current_chapter = 1
        self.max_retries = 3
        self.base_prompt = """
            你是一个玄幻小说大师，请生成包含以下要素的冒险故事：
            1. 主角拥有特殊体质或金手指
            2. 包含至少三个创新修炼体系
            3. 每章必须有战斗情节和宝物获得
            4. 包含意想不到的剧情转折
            5. 对场景和功法进行详细描写
            请用中文以150字左右的段落呈现，结尾给出2-3个选择分支
        """
        
    def generate_story_prompt(self, user_input: str = None) -> List[Dict]:
        """构造带上下文的提示词"""
        system_msg = {
            "role": "system",
            "content": f"{self.base_prompt} 当前是第{self.current_chapter}章，保持故事连贯性。"
        }
        
        messages = [system_msg]
        
        # 添加上下文历史
        if self.story_history:
            messages += self.story_history[-4:]  # 保持最近3轮对话
        
        # 添加用户输入
        if user_input:
            messages.append({"role": "user", "content": user_input})
        else:
            messages.append({"role": "user", "content": "请开始新的故事"})
            
        return messages

class OpenAIClient:
    """处理OpenAI API交互"""
    
    def __init__(self):
        self.model = "gpt-3.5-turbo"
        self.temperature = 0.8
        self.max_tokens = 1500
        
    def generate_story(self, messages: List[Dict]) -> str:
        """调用OpenAI生成故事内容"""
        for _ in range(3):  # 重试机制
            try:
                response = openai.ChatCompletion.create(
                    model=self.model,
                    messages=messages,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens
                )
                return response.choices[0].message['content'].strip()
            except Exception as e:
                print(f"API错误: {e}, 重试中...")
                time.sleep(2)
        return "故事生成失败，请稍后再试"

def display_story(content: str):
    """美化故事显示"""
    print("\n" + "="*50)
    print(f"📖 第{story_mgr.current_chapter}章 📖")
    print("-"*50)
    print(content.replace(". ", ".\n"))
    print("="*50 + "\n")

def main():
    """主程序入口"""
    story_mgr = StoryManager()
    ai_client = OpenAIClient()
    
    print("欢迎来到玄幻小说冒险生成器！")
    print("输入你的选择（数字）或自由输入，输入q退出\n")
    
    user_input = None
    while True:
        # 生成故事内容
        messages = story_mgr.generate_story_prompt(user_input)
        story_content = ai_client.generate_story(messages)
        
        # 处理生成失败的情况
        if "失败" in story_content:
            print(story_content)
            break
            
        display_story(story_content)
        
        # 记录历史
        story_mgr.story_history.extend([
            {"role": "assistant", "content": story_content},
            {"role": "user", "content": user_input} if user_input else None
        ])
        
        # 获取用户输入
        choice = input("请输入你的选择（输入数字或自定义内容）：").strip()
        if choice.lower() == 'q':
            print("\n冒险结束，期待下次再见！")
            break
            
        user_input = f"用户选择：{choice}。请根据这个选择继续发展故事，保持节奏紧凑，并添加新的冲突和奇遇。"
        story_mgr.current_chapter += 1
        
if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n操作已中断")
        sys.exit(0)