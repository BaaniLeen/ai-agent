import os
import discord
import logging
import asyncio
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from mistralai.models.sdkerror import SDKError

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
            try:
                workout_plan = await self.agent.generate_workout(user_id)
            except SDKError as e:
                if "rate limit" in str(e).lower():
                    await ctx.send("😔 Sorry! The AI is a bit overwhelmed right now. Please wait a minute and try again!")
                    return
                raise e

            if not workout_plan or "exercises" not in workout_plan:
                raise ValueError("Invalid workout plan generated")

            logger.info(f"workout_plan: {workout_plan}")    
            plan_display = self.format_workout_plan(workout_plan)
            logger.info(f"plan_display: {plan_display}") 
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
            "exercises": [],
            "status": "in_progress"
        }
        
        await ctx.send("🎯 Let's begin! I'll guide you through each exercise.")
        
        try:
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

Need to stop early? Use `!end_workout` to end your session and save your progress.
""")
                
                def check(m):
                    return m.author == ctx.author and m.channel == ctx.channel
                    
                try:
                    msg = await self.bot.wait_for('message', check=check, timeout=1800)  # 30 min timeout
                    try:
                        performance = await self.agent.evaluate_exercise_performance(
                            user_id,
                            exercise,
                            msg.content
                        )
                    except SDKError as e:
                        if "rate limit" in str(e).lower():
                            await ctx.send("😔 Sorry! The AI is a bit overwhelmed right now. Let me try to evaluate your performance based on basic metrics...")
                            
                            # Basic performance evaluation logic
                            try:
                                # Parse the response in format "SxR @W"
                                parts = msg.content.lower().split('@')
                                sets_reps = parts[0].strip().split('x')
                                completed_sets = int(sets_reps[0])
                                completed_reps = int(sets_reps[1])
                                
                                target_sets = exercise['sets']
                                target_reps = int(exercise['reps'].split('-')[0] if '-' in exercise['reps'] else exercise['reps'])
                                
                                # Simple completion percentage calculation
                                completion_percentage = (completed_sets * completed_reps) / (target_sets * target_reps) * 100
                                
                                if completion_percentage < 70:
                                    performance = "decrease"
                                    await ctx.send("Based on the numbers, this seems challenging. We'll adjust the weight down next time to help you maintain good form.")
                                elif completion_percentage > 90:
                                    performance = "increase"
                                    await ctx.send("Looks like you completed this exercise strong! We'll try increasing the weight next time.")
                                else:
                                    performance = "maintain"
                                    await ctx.send("Solid work! We'll maintain this weight to ensure good form and consistent progress.")
                                    
                            except Exception as parse_error:
                                logger.error(f"Failed to parse exercise performance: {parse_error}")
                                performance = "maintain"
                                await ctx.send("I couldn't quite understand the format of your response. We'll maintain the current weight to be safe. Remember to use the format: sets x reps @ weight (e.g., '3x10 @20lb')")
                        else:
                            raise e
                    
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
                    await ctx.send("Workout session timed out. I'll end this session for you.")
                    await self._end_workout_session(user_id)
                    return
                
            # Update session status to completed
            session_results["status"] = "completed"
            self.agent.db.complete_workout_session(user_id, session_results)
            
            try:
                summary = await self.agent.generate_workout_summary(session_results)
            except SDKError as e:
                if "rate limit" in str(e).lower():
                    summary = "Great work completing your workout! 💪"
                else:
                    raise e
                    
            await ctx.send(f"🎉 Workout complete!\n\n{summary}")
            
        except Exception as e:
            logger.error(f"Failed to complete workout for user {user_id}: {str(e)}")
            await ctx.send("❌ Something went wrong while completing your workout. Please try again later.")

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
            await ctx.send("No progress data available yet. Ready to start? Use `!start_workout` to begin your first workout! 💪")
            return

        # Sort dates and get the most recent ones
        dates = sorted(progress_log.keys(), reverse=True)[:days]
        
        response = f"📊 **Progress Log** (Last {len(dates)} days)\n\n"
        for date in dates:
            entry = progress_log[date]
            status = "✅" if entry["completed"] else "❌"
            response += f"{date}: {status} - {entry['message'][:50]}...\n"

        await ctx.send(response)

    def _get_timezone_from_offset(self, offset_hours, current_time):
        """Convert UTC offset to closest timezone name, considering DST."""
        # Common timezone mappings (offset -> [possible_timezones])
        offset_to_timezone = {
            -12: ["Pacific/Wake"],
            -11: ["Pacific/Pago_Pago"],
            -10: ["Pacific/Honolulu", "America/Adak"],  # Adak observes DST
            -9.5: ["Pacific/Marquesas"],
            -9: ["America/Anchorage", "America/Juneau"],
            -8: ["America/Los_Angeles", "America/Vancouver", "America/Tijuana"],
            -7: ["America/Denver", "America/Phoenix", "America/Edmonton"],  # Phoenix doesn't observe DST
            -6: ["America/Chicago", "America/Mexico_City", "America/Regina"],  # Regina doesn't observe DST
            -5: ["America/New_York", "America/Toronto", "America/Bogota"],  # Bogota doesn't observe DST
            -4: ["America/Halifax", "America/Puerto_Rico"],  # Puerto Rico doesn't observe DST
            -3.5: ["America/St_Johns"],
            -3: ["America/Sao_Paulo", "America/Argentina/Buenos_Aires"],
            -2: ["Atlantic/South_Georgia"],
            -1: ["Atlantic/Azores", "Atlantic/Cape_Verde"],  # Cape Verde doesn't observe DST
            0: ["Europe/London", "UTC"],
            1: ["Europe/Paris", "Europe/Berlin", "Africa/Lagos"],  # Lagos doesn't observe DST
            2: ["Europe/Helsinki", "Europe/Kiev", "Africa/Cairo"],
            3: ["Europe/Moscow", "Asia/Baghdad"],
            3.5: ["Asia/Tehran"],
            4: ["Asia/Dubai", "Asia/Baku"],  # Dubai doesn't observe DST
            4.5: ["Asia/Kabul"],
            5: ["Asia/Karachi", "Asia/Tashkent"],
            5.5: ["Asia/Kolkata", "Asia/Colombo"],
            5.75: ["Asia/Kathmandu"],
            6: ["Asia/Dhaka", "Asia/Almaty"],
            6.5: ["Asia/Yangon"],
            7: ["Asia/Bangkok", "Asia/Ho_Chi_Minh"],
            8: ["Asia/Singapore", "Asia/Shanghai", "Australia/Perth"],
            8.75: ["Australia/Eucla"],
            9: ["Asia/Tokyo", "Asia/Seoul"],
            9.5: ["Australia/Darwin", "Australia/Adelaide"],  # Adelaide observes DST
            10: ["Australia/Sydney", "Australia/Melbourne", "Australia/Brisbane"],  # Brisbane doesn't observe DST
            10.5: ["Australia/Adelaide", "Australia/Lord_Howe"],
            11: ["Pacific/Noumea", "Pacific/Guadalcanal"],
            12: ["Pacific/Auckland", "Pacific/Fiji"],
            13: ["Pacific/Apia", "Pacific/Tongatapu"],
            14: ["Pacific/Kiritimati"]
        }

        # Try each timezone and find the one that matches the current offset
        for tz_name in possible_timezones:
            try:
                tz = ZoneInfo(tz_name)
                # Check if this timezone's current offset matches our target offset
                tz_offset = current_time.astimezone(tz).utcoffset().total_seconds() / 3600
                if abs(tz_offset - offset_hours) < 0.5:  # Allow for small differences
                    return tz_name
            except Exception:
                continue

        # If no matching timezone found, return UTC
        return "UTC"

    @commands.command(name="timezone", help="Set your timezone (defaults to PST)", brief="Set timezone")
    async def set_timezone(self, ctx, timezone: str = None):
        """Set the user's timezone. If no timezone provided, default to US Pacific Time."""
        user_id = ctx.author.id
        user_data = self.agent.db.get_user_data(user_id)
        
        if not user_data or not user_data["onboarded"]:
            await ctx.send("You haven't set up your fitness profile yet! Send me a message to get started.")
            return

        try:
            if timezone is None:
                # Default to US Pacific Time
                timezone = "America/Los_Angeles"
                await ctx.send("ℹ️ Setting your timezone to PST (US Pacific Time). You can change it by using common abbreviations like `!timezone EST` or full names like `!timezone America/New_York`")
            else:
                # Common abbreviation mappings
                abbreviations = {
                    # North America
                    "PST": "America/Los_Angeles",
                    "PDT": "America/Los_Angeles",
                    "MST": "America/Denver",
                    "MDT": "America/Denver",
                    "CST": "America/Chicago",
                    "CDT": "America/Chicago",
                    "EST": "America/New_York",
                    "EDT": "America/New_York",
                    "AST": "America/Halifax",
                    "ADT": "America/Halifax",
                    "NST": "America/St_Johns",
                    "NDT": "America/St_Johns",
                    "AKST": "America/Anchorage",
                    "AKDT": "America/Anchorage",
                    "HST": "Pacific/Honolulu",
                    
                    # Europe
                    "GMT": "UTC",
                    "UTC": "UTC",
                    "WET": "Europe/London",
                    "BST": "Europe/London",
                    "CET": "Europe/Paris",
                    "CEST": "Europe/Paris",
                    "EET": "Europe/Helsinki",
                    "EEST": "Europe/Helsinki",
                    
                    # Asia
                    "MSK": "Europe/Moscow",
                    "IST": "Asia/Kolkata",
                    "GST": "Asia/Dubai",
                    "PKT": "Asia/Karachi",
                    "BST": "Asia/Dhaka",
                    "ICT": "Asia/Bangkok",
                    "CST": "Asia/Shanghai",
                    "HKT": "Asia/Hong_Kong",
                    "JST": "Asia/Tokyo",
                    "KST": "Asia/Seoul",
                    
                    # Australia/Pacific
                    "AWST": "Australia/Perth",
                    "ACST": "Australia/Adelaide",
                    "ACDT": "Australia/Adelaide",
                    "AEST": "Australia/Sydney",
                    "AEDT": "Australia/Sydney",
                    "NZST": "Pacific/Auckland",
                    "NZDT": "Pacific/Auckland",
                    
                    # South America
                    "ART": "America/Argentina/Buenos_Aires",
                    "BRT": "America/Sao_Paulo",
                    "BRST": "America/Sao_Paulo",
                    "CLT": "America/Santiago",
                    "CLST": "America/Santiago",
                    
                    # Africa
                    "WAT": "Africa/Lagos",
                    "CAT": "Africa/Maputo",
                    "EAT": "Africa/Nairobi",
                    "SAST": "Africa/Johannesburg",
                    
                    # Middle East
                    "TRT": "Europe/Istanbul",
                    "IRST": "Asia/Tehran",
                    "IRDT": "Asia/Tehran",
                    
                    "ChST": "Pacific/Guam",  # Chamorro Standard Time
                    "SST": "Pacific/Samoa",   # Samoa Standard Time
                }

                # Convert common abbreviations to canonical names
                timezone = abbreviations.get(timezone.upper(), timezone)

                # Validate timezone
                try:
                    ZoneInfo(timezone)
                except Exception:
                    await ctx.send("❌ Invalid timezone! You can use common abbreviations like `EST`, `PST`, `GMT` or full names like `America/New_York`. See full list here: https://en.wikipedia.org/wiki/List_of_tz_database_time_zones")
                    return

            # Store the timezone
            self.agent.db.update_user_data(user_id, {"timezone": timezone})
            
            # Get a friendly display name and timezone info
            display_name = timezone.split('/')[-1].replace('_', ' ')
            
            # Map canonical names to abbreviations and full names
            timezone_info = {
                # North America
                "America/Los_Angeles": ("PST/PDT", "Pacific Time Zone"),
                "America/Denver": ("MST/MDT", "Mountain Time Zone"),
                "America/Phoenix": ("MST", "Mountain Time Zone (no DST)"),
                "America/Chicago": ("CST/CDT", "Central Time Zone"),
                "America/New_York": ("EST/EDT", "Eastern Time Zone"),
                "America/Halifax": ("AST/ADT", "Atlantic Time Zone"),
                "America/St_Johns": ("NST/NDT", "Newfoundland Time Zone"),
                "America/Anchorage": ("AKST/AKDT", "Alaska Time Zone"),
                "Pacific/Honolulu": ("HST", "Hawaii Time Zone"),
                "America/Tijuana": ("PST/PDT", "Pacific Time Zone"),
                "America/Vancouver": ("PST/PDT", "Pacific Time Zone"),
                "America/Edmonton": ("MST/MDT", "Mountain Time Zone"),
                "America/Regina": ("CST", "Central Time Zone (no DST)"),
                "America/Mexico_City": ("CST/CDT", "Central Time Zone"),
                "America/Toronto": ("EST/EDT", "Eastern Time Zone"),
                "America/Puerto_Rico": ("AST", "Atlantic Time Zone (no DST)"),
                
                # Europe
                "UTC": ("UTC/GMT", "Coordinated Universal Time"),
                "Europe/London": ("GMT/BST", "British Time Zone"),
                "Europe/Paris": ("CET/CEST", "Central European Time Zone"),
                "Europe/Berlin": ("CET/CEST", "Central European Time Zone"),
                "Europe/Helsinki": ("EET/EEST", "Eastern European Time Zone"),
                "Europe/Kiev": ("EET/EEST", "Eastern European Time Zone"),
                "Europe/Moscow": ("MSK", "Moscow Time Zone"),
                
                # Asia
                "Asia/Dubai": ("GST", "Gulf Standard Time"),
                "Asia/Baghdad": ("AST", "Arabia Standard Time"),
                "Asia/Tehran": ("IRST/IRDT", "Iran Time Zone"),
                "Asia/Kabul": ("AFT", "Afghanistan Time Zone"),
                "Asia/Karachi": ("PKT", "Pakistan Time Zone"),
                "Asia/Tashkent": ("UZT", "Uzbekistan Time Zone"),
                "Asia/Kolkata": ("IST", "India Time Zone"),
                "Asia/Colombo": ("IST", "India Time Zone"),
                "Asia/Kathmandu": ("NPT", "Nepal Time Zone"),
                "Asia/Dhaka": ("BST", "Bangladesh Time Zone"),
                "Asia/Yangon": ("MMT", "Myanmar Time Zone"),
                "Asia/Bangkok": ("ICT", "Indochina Time Zone"),
                "Asia/Ho_Chi_Minh": ("ICT", "Indochina Time Zone"),
                "Asia/Singapore": ("SGT", "Singapore Time Zone"),
                "Asia/Shanghai": ("CST", "China Time Zone"),
                "Asia/Hong_Kong": ("HKT", "Hong Kong Time Zone"),
                "Asia/Tokyo": ("JST", "Japan Time Zone"),
                "Asia/Seoul": ("KST", "Korea Time Zone"),
                
                # Australia/Pacific
                "Australia/Perth": ("AWST", "Australian Western Time Zone"),
                "Australia/Darwin": ("ACST", "Australian Central Time Zone (no DST)"),
                "Australia/Adelaide": ("ACST/ACDT", "Australian Central Time Zone"),
                "Australia/Sydney": ("AEST/AEDT", "Australian Eastern Time Zone"),
                "Australia/Melbourne": ("AEST/AEDT", "Australian Eastern Time Zone"),
                "Australia/Brisbane": ("AEST", "Australian Eastern Time Zone (no DST)"),
                "Pacific/Auckland": ("NZST/NZDT", "New Zealand Time Zone"),
                "Pacific/Fiji": ("FJT/FJST", "Fiji Time Zone"),
                "Pacific/Guam": ("ChST", "Chamorro Time Zone"),
                "Pacific/Samoa": ("SST", "Samoa Time Zone"),
                
                # South America
                "America/Argentina/Buenos_Aires": ("ART", "Argentina Time Zone"),
                "America/Sao_Paulo": ("BRT/BRST", "Brasilia Time Zone"),
                "America/Santiago": ("CLT/CLST", "Chile Time Zone"),
                
                # Africa
                "Africa/Lagos": ("WAT", "West Africa Time Zone"),
                "Africa/Cairo": ("EET", "Eastern European Time Zone"),
                "Africa/Maputo": ("CAT", "Central Africa Time Zone"),
                "Africa/Nairobi": ("EAT", "East Africa Time Zone"),
                "Africa/Johannesburg": ("SAST", "South Africa Time Zone"),
                
                # Middle East
                "Europe/Istanbul": ("TRT", "Turkey Time Zone"),
                "Asia/Baku": ("AZT", "Azerbaijan Time Zone"),
                
                # Pacific Islands
                "Pacific/Wake": ("WAKT", "Wake Island Time Zone"),
                "Pacific/Pago_Pago": ("SST", "Samoa Time Zone"),
                "Pacific/Marquesas": ("MART", "Marquesas Time Zone"),
                "Pacific/Noumea": ("NCT", "New Caledonia Time Zone"),
                "Pacific/Guadalcanal": ("SBT", "Solomon Islands Time Zone"),
                "Pacific/Apia": ("WST/WSDT", "West Samoa Time Zone"),
                "Pacific/Tongatapu": ("TOT", "Tonga Time Zone"),
                "Pacific/Kiritimati": ("LINT", "Line Islands Time Zone")
            }
            
            if timezone in timezone_info:
                abbr, full_name = timezone_info[timezone]
                await ctx.send(f"✅ Your timezone has been set to {display_name} ({abbr}, {full_name})!")
            else:
                # For any timezone not in our mapping, try to get the current abbreviation
                try:
                    tz = ZoneInfo(timezone)
                    current_time = datetime.now(tz)
                    abbr = current_time.strftime("%Z")
                    await ctx.send(f"✅ Your timezone has been set to {display_name} ({abbr})!")
                except:
                    await ctx.send(f"✅ Your timezone has been set to {display_name}!")
            
        except Exception as e:
            logger.error(f"Failed to set timezone for user {user_id}: {e}")
            await ctx.send("❌ Something went wrong while setting your timezone. Please try again.")

    async def _end_workout_session(self, user_id: int, force: bool = False) -> bool:
        """Helper function to end a workout session.
        Returns True if workout was ended successfully, False otherwise."""
        user_data = self.agent.db.get_user_data(user_id)
        
        if not user_data or not user_data.get("current_workout"):
            return False
            
        if not force:
            # Save the incomplete workout with status
            session_results = {
                "date": datetime.now().strftime("%Y-%m-%d"),
                "status": "incomplete",
                "exercises": [],
                "notes": "Workout ended early"
            }
            self.agent.db.complete_workout_session(user_id, session_results)
            
        # Clear the current workout regardless
        self.agent.db.update_user_data(user_id, {"current_workout": None})
        return True

    @commands.command(name="end_workout", help="End your current workout session", brief="End workout")
    async def end_workout(self, ctx):
        """End the current workout session."""
        user_id = ctx.author.id
        
        try:
            if await self._end_workout_session(user_id):
                await ctx.send("Workout session ended. Use `!start_workout` when you're ready for your next session! 💪")
            else:
                await ctx.send("You don't have an active workout session to end.")
        except Exception as e:
            logger.error(f"Failed to end workout for user {user_id}: {str(e)}")
            await ctx.send("❌ Something went wrong while ending your workout session.")

    @commands.command(name="reset", help="Reset your fitness tracking and start fresh", brief="Reset fitness tracking")
    async def reset(self, ctx):
        """Reset user's data and restart onboarding process."""
        user_id = ctx.author.id
        
        try:
            # End any ongoing workout first
            await self._end_workout_session(user_id, force=True)
            
            # Then reset the user
            response = await self.agent.reset_user(user_id)
            await ctx.send(response)
        except Exception as e:
            logger.error(f"Failed to reset user {user_id}: {e}")
            await ctx.send("❌ Something went wrong while trying to reset your data. Please try again later.")

    @commands.command(name="reminder", help="Change your daily check-in time (format: HH:MM)", brief="Set check-in time")
    async def set_reminder(self, ctx, new_time: str):
        """Update the user's daily check-in time."""
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

            # Get user's timezone from database or use default
            user_timezone = user_data.get("timezone")
            if not user_timezone:
                user_timezone = "America/Los_Angeles"  # Default to PST
                self.agent.db.update_user_data(user_id, {"timezone": user_timezone})
                await ctx.send("ℹ️ Using PST (US Pacific Time) as your timezone. Use `!timezone` command to change it if needed.")

            # Store the time in the database
            reminder_time = new_time
            self.agent.db.update_user_data(user_id, {
                "reminder_time": reminder_time
            })
            
            # Format time for display (convert to 12-hour format for readability)
            display_time = input_time.strftime("%I:%M %p")
            display_zone = user_timezone.split('/')[-1].replace('_', ' ')
            await ctx.send(f"✅ Your daily check-in time has been set to {display_time} {display_zone}!")
            
        except Exception as e:
            logger.error(f"Failed to set reminder time for user {user_id}: {e}")
            await ctx.send("❌ Something went wrong while setting your reminder time. Please try again.")

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
        try:
            response = await agent.run(message)
        except SDKError as e:
            if "rate limit" in str(e).lower():
                await message.reply("😔 Sorry! The AI is a bit overwhelmed right now. Please wait a minute and try again!")
                return
            raise e
    
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
