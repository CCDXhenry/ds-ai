"""
OpenAI玄幻小说冒险生成器 - 专业版 v4.1
改进内容：
1. 完善所有帮助命令功能
2. 异步文字动画效果
3. 动态语言成就系统
4. 历史记录查看功能
5. 增强输入验证和错误处理
依赖：pip install openai python-dotenv termcolor filelock tenacity
"""

import os
import sys
import time
import json
import asyncio
from enum import Enum
from pathlib import Path
from typing import List, Dict, Optional, Tuple, TypedDict
from termcolor import colored
from openai import AsyncOpenAI, APIError
from dotenv import load_dotenv
from filelock import FileLock, Timeout
from tenacity import (
    retry, 
    stop_after_attempt, 
    wait_exponential, 
    retry_if_exception_type
)

# ...（保留原有类型定义和常量，修改以下部分）...

class GameStateManager:
    def _load_initial_state(self) -> GameState:
        """根据配置语言加载成就"""
        lang = ConfigManager().get('language').value
        return {
            'current_chapter': 0,
            'story_history': [],
            'decision_points': [],
            'achievements': {
                k: (v['name'][lang], False) 
                for k, v in ACHIEVEMENTS.items()
            },
            'achievement_progress': {
                k: {'current': 0, 'target': v['target']} 
                for k, v in ACHIEVEMENTS.items()
            }
        }

class GameInterface:
    async def _animate_text(self, text: str, speed: float = 0.03) -> None:
        """异步文字动画效果"""
        for char in text:
            print(char, end='', flush=True)
            await asyncio.sleep(speed)
        print()

    async def show_history(self, history: List[str]) -> None:
        """显示历史记录"""
        print(colored("\n📜 故事历史：", 'cyan'))
        for i, entry in enumerate(history[-5:], 1):
            print(f"{i}. {entry.split('\n')[0][:50]}...")
            
    async def show_progress(self, progress: Dict) -> None:
        """显示成就进度"""
        lang = self.config.get('language').value
        print(colored("\n🏅 成就进度：", 'cyan'))
        for ach_id, data in ACHIEVEMENTS.items():
            p = progress[ach_id]
            print(f"{data['name'][lang]}: {p['current']}/{p['target']}")

    async def get_choice(self, options: List[str]) -> int:
        """增强的输入处理"""
        while True:
            try:
                choice = input("\n请选择 (1-3/q退出/help查看命令): ").strip().lower()
                
                if choice == 'q':
                    return 0
                if choice == 'help':
                    self._display_help()
                    continue
                if choice == 'save':
                    return -1
                if choice == 'history':
                    return -2
                if choice == 'progress':
                    return -3
                
                # 增强的输入匹配逻辑
                matched = [
                    idx for idx, opt in enumerate(options, 1)
                    if choice in opt.lower() or str(idx) == choice
                ]
                
                if len(matched) == 1:
                    return matched[0]
                    
                raise ValueError
            except ValueError:
                print(colored("无效输入，请输入数字或包含选项关键词", 'yellow'))

class GameController:
    async def _process_choice(self, choice: int, content: str) -> None:
        """处理扩展命令"""
        if choice == 0:
            await self._handle_exit()
            return
            
        if choice == -1:  # 保存命令
            await self._save_game()
            return
        if choice == -2:  # 历史查看
            await self.interface.show_history(self.state_mgr.state['story_history'])
            return
        if choice == -3:  # 进度查看
            await self.interface.show_progress(
                self.state_mgr.state['achievement_progress']
            )
            return
            
        # 原处理逻辑
        self.state_mgr.state['story_history'].append(content)
        self.state_mgr.state['decision_points'].append(choice - 1)
        self.state_mgr.state['current_chapter'] += 1
        self.state_mgr.increment_progress('story_master')

    async def _auto_save(self) -> None:
        """带确认提示的自动保存"""
        if ConfigManager().get('auto_save') and time.time() - self.last_save > ConfigManager().get('save_interval'):
            print(colored("\n⚠️  检测到自动保存时间间隔已到", 'yellow'))
            choice = await self._confirm_prompt("是否立即保存进度？(y/n)")
            if choice:
                await self._save_game()

    async def _confirm_prompt(self, prompt: str) -> bool:
        """通用确认提示"""
        choice = input(colored(f"{prompt}: ", 'yellow')).strip().lower()
        return choice == 'y'

    async def _save_game(self) -> None:
        """带重试机制的保存"""
        try:
            with FileLock("save.lock", timeout=5):
                with open("save.json", 'w', encoding='utf-8') as f:
                    json.dump(self.state_mgr.state, f, ensure_ascii=False, indent=2)
                self.last_save = time.time()
                print(colored("\n✅ 游戏进度已保存！", 'green'))
        except Exception as e:
            if await self._confirm_prompt("保存失败，是否重试？(y/n)"):
                await self._save_game()

    async def _retry_prompt(self) -> bool:
        """带倒计时的重试提示"""
        for i in range(5, 0, -1):
            print(colored(f"\r操作失败，{i}秒后自动重试...", 'yellow'), end='')
            await asyncio.sleep(1)
        print()
        return True

# ...（保留其他原有代码结构）...