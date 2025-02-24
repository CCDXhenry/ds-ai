import os
import random
import time
from typing import Dict, List, Tuple, Optional
from nicegui import ui
from openai import OpenAI, APIError

class FantasyDialogueGenerator:
    """
    玄幻小说对话生成器核心类
    
    功能：
    - 提供角色和情境的输入界面
    - 生成符合玄幻风格的对话
    - 展示生成历史记录
    - 错误处理和加载状态管理
    
    依赖：
    - nicegui >= 1.4.0
    - openai >= 1.12.0 (可选)
    """
    
    def __init__(self):
        self.history: List[Dict[str, str]] = []
        self.client = OpenAI(api_key=os.getenv('OPENAI_API_KEY')) if os.getenv('OPENAI_API_KEY') else None
        self.setup_ui()

    def setup_ui(self) -> None:
        """初始化用户界面组件"""
        with ui.header().classes('bg-blue-100 p-4'):
            ui.label('玄幻小说对话生成器').classes('text-2xl font-bold text-blue-800')
            
        with ui.row().classes('w-full max-w-3xl mx-auto p-6'):
            # 输入区域
            with ui.column().classes('w-1/3 space-y-4'):
                self.role_input = ui.input('角色设定', placeholder='例如：仙尊与魔道圣女').classes('w-full')
                self.context_input = ui.textarea('情境设定', placeholder='例如：在九幽秘境争夺上古神器').classes('w-full h-32')
                self.generate_btn = ui.button('生成对话', on_click=self.generate_dialogue).classes('w-full')
                
            # 输出区域
            with ui.column().classes('w-2/3 space-y-4'):
                self.loading = ui.spinner(size='lg', color='blue').bind_visibility_from(self, 'loading')
                self.dialogue_output = ui.markdown().classes('p-4 bg-gray-50 rounded-lg min-h-48')
                self.error_message = ui.label().classes('text-red-500').bind_visibility_from(self, 'error_message')
                
                # 历史记录
                ui.label('生成历史').classes('text-xl font-semibold mt-4')
                self.history_container = ui.column().classes('space-y-4')

    async def generate_dialogue(self) -> None:
        """生成对话的核心逻辑"""
        try:
            self._validate_inputs()
            self._set_loading_state(True)
            
            prompt = self._build_prompt()
            response = await self._call_llm(prompt)
            
            self._add_to_history(response)
            self._update_display(response)
            
        except ValueError as ve:
            self.error_message = f"输入错误: {str(ve)}"
        except APIError as api_err:
            self.error_message = f"API错误: {api_err.message}"
        except Exception as e:
            self.error_message = f"系统错误: {str(e)}"
        finally:
            self._set_loading_state(False)

    def _validate_inputs(self) -> None:
        """验证用户输入"""
        if not self.role_input.value.strip():
            raise ValueError("必须填写角色设定")
        if not self.context_input.value.strip():
            raise ValueError("必须填写情境设定")

    def _build_prompt(self) -> str:
        """构建LLM提示词"""
        return f"""
        请生成一段符合中国玄幻小说风格的对话。要求：
        1. 角色：{self.role_input.value}
        2. 情境：{self.context_input.value}
        3. 包含至少5轮对话
        4. 使用恰当的文言文与现代汉语结合的表达方式
        5. 每段对话前用角色名称标注
        """

    async def _call_llm(self, prompt: str) -> str:
        """调用大语言模型生成内容"""
        if self.client:
            # 真实API调用
            response = self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
                max_tokens=500
            )
            return response.choices[0].message.content
        else:
            # 模拟数据
            await asyncio.sleep(1)  # 模拟网络延迟
            return self._generate_sample_dialogue()

    def _generate_sample_dialogue(self) -> str:
        """生成示例对话（用于演示或离线模式）"""
        characters = self.role_input.value.split('与') if '与' in self.role_input.value else ['仙尊', '魔尊']
        return f"""
        {characters[0].strip()}：「此物乃我宗门至宝，尔等魔道也敢觊觎？」
        {characters[1].strip()}：（冷笑）「天地灵物，有能者居之！」
        {characters[0].strip()}：（剑指虚空）「那便手底下见真章！」
        ...
        """

    def _add_to_history(self, content: str) -> None:
        """添加记录到历史"""
        self.history.insert(0, {
            'role': self.role_input.value,
            'context': self.context_input.value,
            'content': content
        })
        self._update_history_display()

    def _update_history_display(self) -> None:
        """更新历史记录显示"""
        self.history_container.clear()
        for item in self.history[:3]:
            with ui.card().classes('w-full p-4 bg-white shadow-sm'):
                ui.label(f"角色：{item['role']}").classes('font-medium')
                ui.label(f"情境：{item['context']}").classes('text-sm text-gray-600')
                ui.markdown(item['content']).classes('mt-2')

    def _update_display(self, content: str) -> None:
        """更新主显示区域"""
        self.dialogue_output.content = content
        self.error_message = None

    def _set_loading_state(self, state: bool) -> None:
        """控制加载状态"""
        self.generate_btn.disable = state
        self.loading.visible = state

if __name__ in {"__main__", "__mp_main__"}:
    app = FantasyDialogueGenerator()
    ui.run(
        title="玄幻对话生成器",
        reload=False,
        port=8080,
        favicon="✨",
        dark=False
    )