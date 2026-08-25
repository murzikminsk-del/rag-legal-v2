from bot.handlers import commands, fsm, media, text

routers = [commands.router, fsm.router, media.router, text.router]