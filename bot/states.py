from aiogram.fsm.state import State, StatesGroup

   
class AgentFlow(StatesGroup):
    waiting_for_approval = State()
    
class DocumentFlow(StatesGroup):
    waiting_for_action = State()