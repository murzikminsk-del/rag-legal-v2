from bot.handlers import admin, agent, commands, feedback, media, text

routers = [admin.router, agent.router, commands.router, media.router, text.router, feedback.router]