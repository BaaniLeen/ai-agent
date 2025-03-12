import os
import discord
import logging
import asyncio
from datetime import datetime

from discord.ext import commands, tasks
from dotenv import load_dotenv
from agent import MistralAgent
from database import Database

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

class FitnessTracking(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.agent = agent  # Use the global agent instance

    @commands.command(name="start_workout", help="Start an interactive workout session", brief="Start workout")
    async def start_workout(self, ctx):
        """Start an interactive workout session."""
        user_id = ctx.author.id
        user_data = self.agent.db.get_user_data(user_id)
        
        if not user_data or not user_data["onboarded"]:
            await ctx.send("You haven't set up your fitness profile yet! Send me a message to get started.")
            return
            
        if user_data.get("current_workout"):
            await ctx.send("You have an ongoing workout! Use `!end_workout` to end it first.")
            return
            
        try:
            await ctx.send("🏋️‍♂️ Generating your personalized workout plan...")
            workout_plan = await self.agent.generate_workout(user_id)
            
            if not workout_plan or "exercises" not in workout_plan:
                raise ValueError("Invalid workout plan generated")
                
            plan_display = self.format_workout_plan(workout_plan)
            await ctx.send(f"Here's your workout plan for today:\n\n{plan_display}\n\nReady to start? Type `yes` to begin!")
            
            def check(m):
                return m.author == ctx.author and m.channel == ctx.channel
                
            try:
                msg = await self.bot.wait_for('message', check=check, timeout=300)  # 5 minute timeout
                if msg.content.lower() == 'yes':
                    await self.start_interactive_workout(ctx, workout_plan)
                else:
                    await ctx.send("Workout cancelled. Start when you're ready!")
            except asyncio.TimeoutError:
                await ctx.send("No response received. Workout cancelled. Use `!start_workout` when you're ready!")
                
        except Exception as e:
            logger.error(f"Failed to start workout for user {user_id}: {str(e)}")
            await ctx.send("❌ Something went wrong while setting up your workout. Please try again. If the problem persists, try resetting your fitness profile with `!reset`.")

    async def start_interactive_workout(self, ctx, workout_plan):
        """Handle the interactive workout session."""
        user_id = ctx.author.id
        session_results = {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "exercises": []
        }
        
        await ctx.send("🎯 Let's begin! I'll guide you through each exercise.")
        
        for exercise in workout_plan["exercises"]:
            await ctx.send(f"""
🔄 Next exercise: **{exercise['name']}**
Sets: {exercise['sets']}
Reps: {exercise['reps']}
Weight: {exercise['weight']}

Form cues: {exercise['form_cues']}

Please complete this exercise and tell me what you actually did.
Format: <sets completed>x<reps completed> @<weight used>
Example: "3x10 @20lb" or "2x8 @15lb feeling tired"
""")
            
            def check(m):
                return m.author == ctx.author and m.channel == ctx.channel
                
            try:
                msg = await self.bot.wait_for('message', check=check, timeout=1800)  # 30 min timeout
                performance = await self.agent.evaluate_exercise_performance(
                    user_id,
                    exercise,
                    msg.content
                )
                
                session_results["exercises"].append({
                    "exercise": exercise["name"],
                    "planned": exercise,
                    "actual": msg.content,
                    "evaluation": performance
                })
                
                if performance == "decrease":
                    await ctx.send("I noticed this was challenging. I'll adjust the weight down next time.")
                elif performance == "increase":
                    await ctx.send("Great job! We'll increase the weight next time.")
                else:
                    await ctx.send("Good work! We'll maintain this level for now.")
                    
            except asyncio.TimeoutError:
                await ctx.send("Workout session timed out. Use !end_workout to end the session.")
                return
                
        # Complete the workout
        self.agent.db.complete_workout_session(user_id, session_results)
        
        summary = await self.agent.generate_workout_summary(session_results)
        await ctx.send(f"🎉 Workout complete!\n\n{summary}")

    def format_workout_plan(self, plan):
        """Format the workout plan for display"""
        output = "**Today's Workout Plan**\n\n"
        
        if plan.get("warmup"):
            output += "🔥 **Warmup**:\n"
            output += plan["warmup"] + "\n\n"
            
        output += "💪 **Main Workout**:\n"
        for exercise in plan["exercises"]:
            output += f"• {exercise['name']}\n"
            output += f"  - {exercise['sets']} sets × {exercise['reps']} reps @ {exercise['weight']}\n"
            
        if plan.get("cooldown"):
            output += "\n🧊 **Cooldown**:\n"
            output += plan["cooldown"]
            
        return output

    @commands.command(name="streak", help="Check your fitness progress and streak", brief="Check your streak")
    async def streak(self, ctx):
        """Show the user's fitness progress and streak information."""
        user_id = ctx.author.id
        user_data = self.agent.db.get_user_data(user_id)
        
        if not user_data or not user_data["onboarded"]:
            await ctx.send("You haven't set up your fitness profile yet! Send me a message to get started.")
            return

        response = (
            f"🎯 **Your Fitness Goal**: {user_data['fitness_goal']}\n\n"
            f"💪 **Current Streak**: {user_data['current_streak']} days\n"
            f"🏆 **Longest Streak**: {user_data['longest_streak']} days\n\n"
            f"📊 **Your Milestones**:\n{user_data['milestones']}\n\n"
            f"⏰ **Daily Check-in Time**: {user_data['reminder_time']}"
        )
        await ctx.send(response)

    @commands.command(name="progress", help="View your progress log (default: last 7 days)", brief="View progress log")
    async def progress(self, ctx, days: int = 7):
        """Show the user's progress log for the specified number of days."""
        user_id = ctx.author.id
        user_data = self.agent.db.get_user_data(user_id)
        
        if not user_data or not user_data["onboarded"]:
            await ctx.send("You haven't set up your fitness profile yet! Send me a message to get started.")
            return

        progress_log = user_data["progress_log"]
        if not progress_log:
            await ctx.send("No progress data available yet. Keep working on your fitness goals!")
            return

        # Sort dates and get the most recent ones
        dates = sorted(progress_log.keys(), reverse=True)[:days]
        
        response = f"📊 **Progress Log** (Last {len(dates)} days)\n\n"
        for date in dates:
            entry = progress_log[date]
            status = "✅" if entry["completed"] else "❌"
            response += f"{date}: {status} - {entry['message'][:50]}...\n"

        await ctx.send(response)

    @commands.command(name="reminder", help="Change your daily check-in time (format: HH:MM)", brief="Set check-in time")
    async def set_reminder(self, ctx, new_time: str):
        """Update the user's daily check-in time, using their Discord timezone."""
        user_id = ctx.author.id
        user_data = self.agent.db.get_user_data(user_id)
        
        if not user_data or not user_data["onboarded"]:
            await ctx.send("You haven't set up your fitness profile yet! Send me a message to get started.")
            return

        try:
            # Parse the time
            try:
                input_time = datetime.strptime(new_time, "%H:%M")
            except ValueError:
                await ctx.send("❌ Please use the 24-hour format HH:MM (e.g., 09:00 or 14:30)")
                return

            # Get user's timezone from Discord
            user = ctx.author
            if not user.timezone:
                await ctx.send("❌ Please set your timezone in Discord settings first! This helps me send reminders at the right time for you.")
                return

            # Store the time in the user's timezone
            reminder_time = new_time
            self.agent.db.update_user_data(user_id, {
                "reminder_time": reminder_time,
                "timezone": str(user.timezone)
            })
            
            # Format time for display (convert to 12-hour format for readability)
            display_time = input_time.strftime("%I:%M %p")
            await ctx.send(f"✅ Your daily check-in time has been set to {display_time} in your timezone ({user.timezone})!")
            
        except Exception as e:
            logger.error(f"Failed to set reminder time for user {user_id}: {e}")
            await ctx.send("❌ Something went wrong while setting your reminder time. Please try again.")

    @commands.command(name="reset", help="Reset your fitness tracking and start fresh", brief="Reset fitness tracking")
    async def reset(self, ctx):
        """Reset user's data and restart onboarding process."""
        user_id = ctx.author.id
        
        try:
            response = await self.agent.reset_user(user_id)
            await ctx.send(response)
        except Exception as e:
            logger.error(f"Failed to reset user {user_id}: {e}")
            await ctx.send("❌ Something went wrong while trying to reset your data. Please try again later.")

@bot.event
async def on_ready():
    """
    Called when the client is done preparing the data received from Discord.
    Prints message on terminal when bot successfully connects to discord.

    https://discordpy.readthedocs.io/en/latest/api.html#discord.on_ready
    """
    logger.info(f"{bot.user} has connected to Discord!")
     # If the task is running due to a previous session, stop it first
    if check_reminders.is_running():
        check_reminders.cancel()
    check_reminders.start()


@tasks.loop(minutes=5)  # Check every 5 minutes
async def check_reminders():
    """Check if any users need reminders and send them."""
    all_users = list(agent.db.get_all_users())  # Convert cursor to list
    logger.info(f"Checking reminders for {len(all_users)} users...")
    
    # Log summary of each user's state
    for user_data in all_users:
        logger.info(f"User {user_data['_id']}: "
                   f"habit='{user_data.get('habit_goal', 'Not set')}', "
                   f"reminder_time={user_data.get('reminder_time', 'Not set')}, "
                   f"last_check_in={user_data.get('last_check_in', 'Never')}, "
                   f"streak={user_data.get('current_streak', 0)}")
        
        user_id = user_data["_id"]
        try:
            if agent.should_send_reminder(user_id):
                user = await bot.fetch_user(user_id)
                if user:
                    await agent.send_reminder(user_id, user)
        except Exception as e:
            logger.error(f"Failed to process reminder for user {user_id}: {e}")


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


# Add this right before bot.run(token)
async def setup():
    await bot.add_cog(FitnessTracking(bot))

# Modify the bot.run line to setup the cog
bot.setup_hook = setup

print(f"Token: {token}...")  # Print only the first few characters for debugging
# Start the bot, connecting it to the gateway
bot.run(token)
