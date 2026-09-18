from aiogram.fsm.state import State, StatesGroup


class AskFlow(StatesGroup):
    waiting_for_topic = State()
    waiting_for_question = State()
    confirming = State()
    
class AgentFlow(StatesGroup):
    waiting_for_approval = State()
    
class DocumentFlow(StatesGroup):
    waiting_for_action = State()