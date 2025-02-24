"""
OpenAI玄幻小说冒险生成器 - 增强版
新增功能：
1. 用户配置系统
2. 多结局系统
3. 自动存档功能
4. 输入验证增强
5. 输出格式化增强
依赖：pip install openai python-dotenv termcolor
"""

import os
import sys
import time
import json
from typing import List, Dict, Optional
from pathlib import Path
from termcolor import colored
import openai
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")

class UserConfig:
    """用户配置管理系统"""
    
    def __init__(self):
        self.config = {
            'model': "gpt-3.5-turbo",
            'temperature': 0.8,
            'max_tokens': 1500,
            'auto_save': True,
            'max_history': 5
        }
        
    def update_config(self, key: str, value: str):
        """更新配置参数"""
        if key in self.config:
            # 类型转换处理
            original_type = type(self.config[key])
            try:
                self.config[key] = original_type(value)
            except ValueError:
                print(f"错误：{value} 不能转换为{original_type}类型")
                
class StoryManager:
    """管理故事生成状态和上下文"""
    
    def __init__(self, config: UserConfig):
        self.story_history: List[Dict] = []
        self.current_chapter = 1
        self.max_retries = 3
        self.config = config
        self.decision_points = []  # 记录关键决策点
        self.base_prompt = """
            你是一个玄幻小说大师，请生成包含以下要素的冒险故事：
            1. 主角拥有特殊体质或金手指
            2. 包含至少三个创新修炼体系
            3. 每章必须有战斗情节和宝物获得
            4. 包含意想不到的剧情转折
            5. 对场景和功法进行详细描写
            请用中文以150字左右的段落呈现，结尾给出2-3个选择分支
        """
        self.achievements = set()  # 成就系统
        
    def generate_story_prompt(self, user_input: str = None) -> List[Dict]:
        """构造带上下文的提示词"""
        system_msg = {
            "role": "system",
            "content": f"{self.base_prompt} 当前是第{self.current_chapter}章，保持故事连贯性。"
        }
        
        messages = [system_msg]
        
        # 添加上下文历史（根据配置长度）
        if self.story_history:
            messages += self.story_history[-self.config.config['max_history']*2:]
        
        # 添加用户输入
        if user_input:
            messages.append({"role": "user", "content": user_input})
        else:
            messages.append({"role": "user", "content": "请开始新的故事"})
            
        return messages
    
    def save_progress(self, filename: str = "autosave.json"):
        """保存当前进度到文件"""
        save_data = {
            "chapter": self.current_chapter,
            "history": self.story_history,
            "decisions": self.decision_points,
            "achievements": list(self.achievements)
        }
        
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(save_data, f, ensure_ascii=False)
            print(colored(f"\n进度已自动保存到 {filename}", 'green'))
        except Exception as e:
            print(colored(f"\n保存失败: {e}", 'red'))
            
    def load_progress(self, filename: str) -> bool:
        """从文件加载进度"""
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self.current_chapter = data['chapter']
            self.story_history = data['history']
            self.decision_points = data['decisions']
            self.achievements = set(data['achievements'])
            return True
        except Exception as e:
            print(colored(f"\n加载失败: {e}", 'red'))
            return False

class OpenAIClient:
    """处理OpenAI API交互"""
    
    def __init__(self, config: UserConfig):
        self.config = config
        
    def generate_story(self, messages: List[Dict]) -> Optional[str]:
        """调用OpenAI生成故事内容"""
        for retry in range(3):
            try:
                response = openai.ChatCompletion.create(
                    model=self.config.config['model'],
                    messages=messages,
                    temperature=self.config.config['temperature'],
                    max_tokens=self.config.config['max_tokens']
                )
                return response.choices[0].message['content'].strip()
            except openai.error.RateLimitError:
                wait_time = (retry + 1) * 5
                print(colored(f"速率限制已达，{wait_time}秒后重试...", 'yellow'))
                time.sleep(wait_time)
            except Exception as e:
                print(colored(f"API错误: {e}", 'red'))
            return None

class StoryFormatter:
    """处理故事内容的格式化和显示"""
    
    @staticmethod
    def display_story(content: str, chapter: int):
        """美化故事显示"""
        print("\n" + colored("="*50, 'cyan'))
        print(colored(f"📖 第{chapter}章 📖", 'yellow', attrs=['bold']))
        print(colored("-"*50, 'cyan'))
        # 处理段落格式
        formatted = content.replace(". ", ".\n").replace("！", "！\n")
        paragraphs = [p.strip() for p in formatted.split("\n") if p.strip()]
        for idx, para in enumerate(paragraphs):
            if idx == len(paragraphs)-1:
                print(colored(para, 'magenta'))  # 最后一段是选项
            else:
                print(colored(para, 'white'))
        print(colored("="*50 +