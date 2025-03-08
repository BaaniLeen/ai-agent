import os
import discord
import logging
import asyncio
from datetime import datetime

from discord.ext import commands, tasks
from dotenv import load_dotenv
from agent import MistralAgent

PREFIX = "!"

# Setup logging
logger = logging.getLogger("discord")

# Load the environment variables
load_dotenv()

MAX_MESSAGE_LENGTH = 2000

# Create the bot with all intents
# The message content and members intent must be enabled in the Discord Developer Portal for the bot to work.
intents = discord.Intents.all()
bot = commands.Bot(command_prefix=PREFIX, intents=intents)

# Import the Mistral agent from the agent.py file
agent = MistralAgent()

# Get the token from the environment variables
token = os.getenv("DISCORD_TOKEN")


@bot.event
async def on_ready():
    """
    Called when the client is done preparing the data received from Discord.
    Prints message on terminal when bot successfully connects to discord.

    https://discordpy.readthedocs.io/en/latest/api.html#discord.on_ready
    """
    logger.info(f"{bot.user} has connected to Discord!")
    check_reminders.start()


@tasks.loop(minutes=5)  # Check every 5 minutes
async def check_reminders():
    """Check if any users need reminders and send them."""
    for user_id in agent.user_data:
        if agent.should_send_reminder(user_id):
            try:
                user = await bot.fetch_user(user_id)
                if user:
                    await agent.send_reminder(user_id, user)
            except Exception as e:
                logger.error(f"Failed to send reminder to user {user_id}: {e}")


@bot.event
async def on_message(message: discord.Message):
    """
    Called when a message is sent in any channel the bot can see.

    https://discordpy.readthedocs.io/en/latest/api.html#discord.on_message
    """

    # Don't delete this line! It's necessary for the bot to process commands.
    await bot.process_commands(message)

    # Ignore messages from self or other bots to prevent infinite loops.
    if message.author.bot or message.content.startswith("!"):
        return

    # Process the message with the agent
    logger.info(f"Processing message from {message.author}: {message.content}")
    
    # Show typing indicator to make the bot feel more responsive
    async with message.channel.typing():
        response = await agent.run(message)
    
    # Check if the message exceeds the character limit
    if len(response) > MAX_MESSAGE_LENGTH:
        # Split the response into smaller parts if it exceeds the limit
        for i in range(0, len(response), MAX_MESSAGE_LENGTH):
            await message.channel.send(response[i:i + MAX_MESSAGE_LENGTH])
    else:
        await message.reply(response)


# Commands


# This example command is here to show you how to add commands to the bot.
# Run !ping with any number of arguments to see the command in action.
# Feel free to delete this if your project will not need commands.
@bot.command(name="ping", help="Pings the bot.")
async def ping(ctx, *, arg=None):
    if arg is None:
        await ctx.send("Pong!")
    else:
        await ctx.send(f"Pong! Your argument was {arg}")


@bot.command(name="streak", help="Check your current streak and progress")
async def streak(ctx):
    """Show the user's current streak and progress information."""
    user_id = ctx.author.id
    if user_id not in agent.user_data or not agent.user_data[user_id]["onboarded"]:
        await ctx.send("You haven't set up your habit tracking yet! Send me a message to get started.")
        return

    user_data = agent.user_data[user_id]
    response = (
        f"🎯 **Your Habit Goal**: {user_data['habit_goal']}\n\n"
        f"📊 **Current Streak**: {user_data['current_streak']} days\n"
        f"🏆 **Longest Streak**: {user_data['longest_streak']} days\n\n"
        f"🎯 **Your Milestones**:\n{user_data['milestones']}\n\n"
        f"⏰ **Daily Check-in Time**: {user_data['reminder_time']}"
    )
    await ctx.send(response)


@bot.command(name="reminder", help="Change your daily reminder time (format: HH:MM)")
async def set_reminder(ctx, new_time: str):
    """Update the user's daily reminder time."""
    user_id = ctx.author.id
    if user_id not in agent.user_data or not agent.user_data[user_id]["onboarded"]:
        await ctx.send("You haven't set up your habit tracking yet! Send me a message to get started.")
        return

    try:
        # Validate time format
        datetime.strptime(new_time, "%H:%M")
        agent.user_data[user_id]["reminder_time"] = new_time
        await ctx.send(f"✅ Your daily reminder time has been updated to {new_time}!")
    except ValueError:
        await ctx.send("❌ Please use the format HH:MM (e.g., 09:00 or 14:30)")


@bot.command(name="progress", help="View your progress log")
async def progress(ctx, days: int = 7):
    """Show the user's progress log for the specified number of days."""
    user_id = ctx.author.id
    if user_id not in agent.user_data or not agent.user_data[user_id]["onboarded"]:
        await ctx.send("You haven't set up your habit tracking yet! Send me a message to get started.")
        return

    progress_log = agent.user_data[user_id]["progress_log"]
    if not progress_log:
        await ctx.send("No progress data available yet. Keep working on your habit!")
        return

    # Sort dates and get the most recent ones
    dates = sorted(progress_log.keys(), reverse=True)[:days]
    
    response = f"📊 **Progress Log** (Last {len(dates)} days)\n\n"
    for date in dates:
        entry = progress_log[date]
        status = "✅" if entry["completed"] else "❌"
        response += f"{date}: {status} - {entry['message'][:50]}...\n"

    await ctx.send(response)


print(f"Token: {token}...")  # Print only the first few characters for debugging
# Start the bot, connecting it to the gateway
bot.run(token)
