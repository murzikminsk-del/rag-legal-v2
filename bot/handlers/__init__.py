from bot.handlers import commands, fsm, text

routers = [commands.router, fsm.router, text.router]