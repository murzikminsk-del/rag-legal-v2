from bot.handlers import admin, agent, commands, feedback, fsm, media, text

routers = [admin.router, agent.router, commands.router, fsm.router, media.router, text.router, feedback.router]