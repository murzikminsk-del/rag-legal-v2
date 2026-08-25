from bot.handlers import admin, commands, feedback, fsm, media, text

routers = [admin.router, commands.router, fsm.router, media.router, text.router, feedback.router]