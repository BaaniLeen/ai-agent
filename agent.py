import os
from mistralai import Mistral
import discord
from datetime import datetime, timedelta
import logging
from database import Database
from typing import Dict, Any
from zoneinfo import ZoneInfo

MISTRAL_MODEL = "mistral-large-latest"
SYSTEM_PROMPT = """You are a knowledgeable and motivating fitness coach. Help users achieve their gym goals by:
1. Setting realistic fitness milestones based on their goals
2. Tracking workout progress and celebrating consistency
3. Providing form tips and exercise suggestions
4. Celebrating fitness achievements, no matter how small
5. Helping users overcome plateaus and challenges
6. Ensuring safe progression and proper recovery
Make sure your responses are less than 2000 words in length."""

COMMANDS_HELP = """
Here are all the available commands:
• Just type a message normally to chat with me about your workout progress
• `!start_workout` - Start an interactive workout session
• `!end_workout` - End your current workout session
• `!streak` - Check your current workout streak and progress
• `!progress [days]` - View your workout log (default: last 7 days)
• `!reminder HH:MM` - Change your daily check-in time (e.g., !reminder 20:00)
• `!timezone [zone]` - Set your timezone (defaults to PST, e.g., !timezone EST or !timezone America/New_York)
• `!reset` - Reset your fitness tracking and start fresh
• `!help` - Show this help message
"""

# Update the ONBOARDING_PROMPT to include commands
ONBOARDING_PROMPT = """Welcome to your fitness journey! 🏋️‍♂️ I'm your AI gym coach.

⚠️ **Important Disclaimer**:
I am an AI assistant, not a certified fitness expert or medical professional. The workout suggestions and advice I provide are general in nature and may not be suitable for everyone. Please:
• Consult with healthcare providers before starting any new exercise program
• Listen to your body and don't push beyond your limits
• Seek professional guidance for proper form and technique
• Use this bot as a supplementary tool, not as a replacement for professional advice

To get started, please tell me:

1. Your main fitness goal (e.g., "increase bicep size", "lose 100 pounds from 300 pounds")
2. Your current stats (weight, height, any relevant measurements)
3. Your gym experience level (beginner/intermediate/advanced)
4. Any injuries or limitations I should know about
5. What time would you like me to check in with you daily? (e.g., '8:00 PM')
6. What timezone are you in? (e.g., 'PST', 'EST', or full names like 'America/New_York')

""" + COMMANDS_HELP

REMINDER_MESSAGE = """Hey fitness warrior! 💪 I noticed you haven't checked in about your workout today. How's your progress with "{fitness_goal}"? 

Remember:
• Rest days are important too! If today is a rest day, just let me know
• Even a short workout is better than no workout
• We're building long-term habits here

Ready for a workout? Type `!start_workout` to begin an interactive workout session! 🎯"""

COMPLETION_ANALYZER_PROMPT = """You are a fitness progress analyzer. 
Your task is to determine if a user's message indicates they completed their workout or if it was a planned rest day.
Consider that rest days, when planned and communicated, count as completed.

Interpret casual positive or neutral expressions as completed workouts. For example:
- "decent workout today" = completed
- "okay session" = completed
- "alright workout" = completed
- "not bad" = completed
- "could be better but got it done" = completed

Only mark as incomplete if the user clearly indicates they:
1. Missed their workout entirely
2. Had an unplanned skip day
3. Explicitly states they did not work out

Respond with EXACTLY one word: either 'completed' or 'incomplete'.
Consider context and nuance rather than just looking for specific words.

Make sure your responses are less than 2000 words in length."""

STREAK_MILESTONES = {
    3: "💪 3-day streak! Building that gym consistency!",
    7: "🔥 One week strong! Your dedication is showing!",
    14: "⚡ Two week warrior! You're making this a lifestyle!",
    21: "💫 21 days! Your commitment to fitness is inspiring!",
    30: "🏆 30-day champion! You're a true fitness warrior!",
    60: "👑 60 days! You're transforming your life!",
    90: "🌟 90-day legend! This is officially your lifestyle now!"
}

WORKOUT_GENERATOR_PROMPT = """You are an expert fitness trainer. Generate a 1-hour workout plan based on:
1. User's goal: {goal}
2. Experience level: {experience}
3. Previous performance: {history}
4. Any limitations: {limitations}

Format the response as a JSON-like structure with exercises, sets, reps, and weights.
Include a mix of:
- 5-10 min warmup (dynamic stretches, light cardio)
- 2-3 main compound exercises
- 3-4 targeted exercises for their specific goals
- 5 min cooldown
Each exercise should include clear instructions and form cues.

Example format:
{
    "warmup": "5 minutes light treadmill, arm circles, leg swings, etc.",
    "exercises": [
        {
            "name": "Barbell Bench Press",
            "sets": 3,
            "reps": "8-10",
            "weight": "135lb",
            "form_cues": "Retract shoulder blades, feet planted, control the descent"
        }
    ],
    "cooldown": "5 minutes stretching focusing on worked muscle groups"
}

Make sure your responses are less than 1000 words in length.
"""

EXERCISE_EVALUATION_PROMPT = """You are a fitness performance analyzer.
Target: {target_performance}
Actual: {actual_performance}
Previous max: {previous_max}

Evaluate if this performance indicates:
1. Need to decrease weight/intensity (if below 70% completion or showing poor form)
2. Good to maintain current level (if 70-90% completion with good form)
3. Ready to increase weight/intensity (if >90% completion with good form)

Consider:
- Form and technique mentioned
- Reported effort level
- Comparison to previous performances
- Safety first - when in doubt, maintain current level

Respond with EXACTLY one word: 'decrease', 'maintain', or 'increase'

Make sure your responses are less than 1000 words in length.
"""

# Setup logging
logger = logging.getLogger("discord")

class MistralAgent:
    def __init__(self):
        MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
        self.client = Mistral(api_key=MISTRAL_API_KEY)
        self.db = Database()

    def update_streak(self, user_id, completed=True):
        """Update user's streak and check for milestone achievements"""
        user_data = self.db.get_user_data(user_id)
        
        if completed:
            new_streak = user_data["current_streak"] + 1
            longest_streak = max(user_data["longest_streak"], new_streak)
            
            self.db.update_user_data(user_id, {
                "current_streak": new_streak,
                "longest_streak": longest_streak
            })
            
            # Check for streak milestones
            if new_streak in STREAK_MILESTONES:
                return STREAK_MILESTONES[new_streak]
        else:
            self.db.update_user_data(user_id, {"current_streak": 0})
        return None

    def should_send_reminder(self, user_id):
        """Check if we should send a reminder to the user"""
        logger.info(f"Should send reminder?")
        user_data = self.db.get_user_data(user_id)
        if not user_data or not user_data["onboarded"] or not user_data["timezone"]:
            return False
        
        last_check_in = datetime.strptime(user_data["last_check_in"], "%Y-%m-%d")
        last_reminder = datetime.strptime(user_data.get("last_reminder_sent", "2000-01-01"), "%Y-%m-%d")
        reminder_time = datetime.strptime(user_data["reminder_time"], "%H:%M").time()
        
        # Get current time in user's timezone
        user_tz = ZoneInfo(user_data["timezone"])
        current_time = datetime.now(user_tz)
        current_date = current_time.date()
        
        logger.info(f"last_check_in: {last_check_in}; reminder_time: {reminder_time}; current_time:{current_time} (timezone: {user_data['timezone']})")
        logger.info(f"last_reminder: {last_reminder.date()}; current_date: {current_date}")
        
        # Only send reminder if:
        # 1. It's past the reminder time
        # 2. User hasn't checked in today
        # 3. We haven't sent a reminder today
        if (current_time.time() > reminder_time and 
            last_check_in.date() < current_date and 
            last_reminder.date() < current_date):
            # Update last reminder date
            self.db.update_user_data(user_id, {"last_reminder_sent": current_date.strftime("%Y-%m-%d")})
            return True
        return False

    async def send_reminder(self, user_id, channel):
        """Send a reminder message to the user"""
        logger.info(f"Sending reminder for user: {user_id} to channel: {channel}")
        user_data = self.db.get_user_data(user_id)
        fitness_goal = user_data["fitness_goal"]
        reminder = REMINDER_MESSAGE.format(fitness_goal=fitness_goal)
        await channel.send(reminder)

    async def run(self, message: discord.Message):
        user_id = message.author.id
        current_date = datetime.now().strftime("%Y-%m-%d")
        
        # Get or create user data
        user_data = self.db.get_user_data(user_id)
        if not user_data:
            user_data = self.db.create_user(user_id)
            # For new users, send the onboarding prompt
            self.db.update_conversation_history(user_id, {
                "role": "assistant",
                "content": ONBOARDING_PROMPT,
                "date": current_date
            })
            return ONBOARDING_PROMPT  # Early return for new users
        
        # Add message to conversation history
        message_entry = {
            "role": "user",
            "content": message.content,
            "date": current_date
        }
        self.db.update_conversation_history(user_id, message_entry)
        
        # Handle onboarding response
        if not user_data["onboarded"]:
            # Extract time and timezone from the message
            time_zone_extraction_prompt = """You are a time and timezone parser. Extract both the time and timezone from this message.
For time: Convert to 24-hour format (HH:MM). If no time found, use "20:00".
For timezone: Look for common abbreviations (PST, EST, etc.) or full names. If no timezone found, use "America/Los_Angeles".
Respond in exactly this format:
TIME|TIMEZONE
Examples:
"I want to work out at 8:30 AM EST" -> "08:30|America/New_York"
"9pm works for me, I'm in Pacific time" -> "21:00|America/Los_Angeles"
"8 in the morning, CST" -> "08:00|America/Chicago"
"""
            messages = [
                {"role": "system", "content": time_zone_extraction_prompt},
                {"role": "user", "content": message.content}
            ]
            
            extraction_response = await self.client.chat.complete_async(
                model=MISTRAL_MODEL,
                messages=messages,
            )
            
            try:
                time_str, timezone_str = extraction_response.choices[0].message.content.strip().split('|')
                # Validate the time format
                datetime.strptime(time_str, "%H:%M")
                # Validate timezone
                ZoneInfo(timezone_str)
                
                self.db.update_user_data(user_id, {
                    "reminder_time": time_str,
                    "timezone": timezone_str
                })
                logger.info(f"Set reminder time to {time_str} and timezone to {timezone_str}")
            except Exception as e:
                logger.error(f"Invalid format from LLM: {extraction_response.choices[0].message.content}, using defaults")
                self.db.update_user_data(user_id, {
                    "reminder_time": "20:00",
                    "timezone": "America/Los_Angeles"
                })
            
            # Update user data for onboarding
            self.db.update_user_data(user_id, {
                "fitness_goal": message.content,
                "onboarded": True
            })
            
            # Get milestones
            milestone_prompt = f"Based on the user's fitness goal: '{message.content}', suggest 3 achievable milestones. Format as a list."
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": milestone_prompt}
            ]
            
            milestone_response = await self.client.chat.complete_async(
                model=MISTRAL_MODEL,
                messages=messages,
            )
            
            milestones = milestone_response.choices[0].message.content
            self.db.update_user_data(user_id, {"milestones": milestones})
            
            # Get fresh user data to ensure we have the latest reminder time
            fresh_user_data = self.db.get_user_data(user_id)
            
            # Format time for display (convert to 12-hour format)
            display_time = datetime.strptime(fresh_user_data['reminder_time'], "%H:%M").strftime("%I:%M %p")
            
            response = f"Thank you for sharing! I've noted your fitness goal:\n\n'{message.content}'\n\nHere are some milestones we can work toward:\n\n{milestones}\n\nI'll check in with you daily at {display_time} to track your progress. Ready to start your first workout? Type `!start_workout` to begin, or tell me how your recent workout went! 💪"
            
            # Store response in history
            self.db.update_conversation_history(user_id, {
                "role": "assistant",
                "content": response,
                "date": current_date
            })
            
            self.db.update_user_data(user_id, {"last_check_in": current_date})
            return response
        
        # For subsequent conversations
        user_data = self.db.get_user_data(user_id)  # Get fresh data
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "system", "content": f"User's fitness goal: {user_data['fitness_goal']}"},
            {"role": "system", "content": f"Milestones: {user_data['milestones']}"},
            {"role": "system", "content": f"Current streak: {user_data['current_streak']} days"},
            {"role": "system", "content": f"Longest streak: {user_data['longest_streak']} days"},
            {"role": "system", "content": f"Last check-in: {user_data['last_check_in']}"}
        ]
        
        # Add conversation history
        history = user_data["conversation_history"][-10:]
        for entry in history:
            if entry["role"] in ["user", "assistant"]:
                messages.append({"role": entry["role"], "content": entry["content"]})
        
        messages.append({"role": "user", "content": message.content})
        
        # Check for new day
        if user_data["last_check_in"] != current_date:
            messages.append({"role": "system", "content": "This is a new day. Ask about progress on their workout and provide encouragement. If they completed their workout, celebrate. If not, show understanding and help identify obstacles."})
            self.db.update_user_data(user_id, {"last_check_in": current_date})
        
        response = await self.client.chat.complete_async(
            model=MISTRAL_MODEL,
            messages=messages,
        )
        
        response_message = response.choices[0].message.content
        
        # Use LLM to determine if the message indicates completion
        completion_check_messages = [
            {"role": "system", "content": COMPLETION_ANALYZER_PROMPT},
            {"role": "system", "content": f"The user's fitness goal is: {user_data['fitness_goal']}"},
            {"role": "user", "content": message.content}
        ]
        
        completion_response = await self.client.chat.complete_async(
            model=MISTRAL_MODEL,
            messages=completion_check_messages,
        )
        
        completion_result = completion_response.choices[0].message.content.strip().lower()
        
        if completion_result == 'completed':
            streak_milestone = self.update_streak(user_id, completed=True)
            if streak_milestone:
                response_message = f"{response_message}\n\n{streak_milestone}"
        elif completion_result == 'incomplete':
            self.update_streak(user_id, completed=False)
        
        # Update progress log
        self.db.update_progress_log(user_id, current_date, {
            "message": message.content,
            "completed": self.db.get_user_data(user_id)["current_streak"] > 0
        })
        
        # Store response in history
        self.db.update_conversation_history(user_id, {
            "role": "assistant",
            "content": response_message,
            "date": current_date
        })
        
        return response_message

    async def reset_user(self, user_id: int) -> str:
        """Reset a user's data and restart their onboarding process."""
        # First check if user exists in database
        user_data = self.db.get_user_data(user_id)
        if not user_data:
            return "You don't have any fitness tracking data to reset!"
        
        # Delete user's data from database
        self.db.delete_user(user_id)
        
        # Create new user entry and get onboarding prompt
        user_data = self.db.create_user(user_id)
        self.db.update_conversation_history(user_id, {
            "role": "assistant",
            "content": ONBOARDING_PROMPT,
            "date": datetime.now().strftime("%Y-%m-%d")
        })
        
        return "✨ Your fitness tracking data has been reset! Let's start fresh.\n\n" + ONBOARDING_PROMPT

    async def generate_workout(self, user_id: int) -> Dict[str, Any]:
        """Generate a personalized workout plan"""
        user_data = self.db.get_user_data(user_id)
        logger.info(f"User data: {user_data}")

        # Get exercise history for progressive overload
        exercise_history = user_data.get("exercise_history", {})
        goal = user_data.get("fitness_goal", "Not specified")
        experience_level = user_data.get("experience_level", "Not specified")
        limitations = user_data.get("limitations", "Not specified")

        example_format = {
            "warmup": "5 minutes light treadmill, arm circles, leg swings, etc.",
            "exercises": [
                {
                    "name": "Barbell Bench Press",
                    "sets": 3,
                    "reps": "8-10",
                    "weight": "135lb",
                    "form_cues": "Retract shoulder blades, feet planted, control the descent"
                }
            ],
            "cooldown": "5 minutes stretching focusing on worked muscle groups"
        }

        workout_generator_prompt = f"""You are an expert fitness trainer. Generate a 1-hour workout plan based on:
1. User's goal: {str(goal)}
2. Experience level: {str(experience_level)}
3. Previous performance: {str(exercise_history)}
4. Any limitations: {str(limitations)}

Format the response as a JSON-like structure with exercises, sets, reps, and weights.
Include a mix of:
- 5-10 min warmup (dynamic stretches, light cardio)
- 2-3 main compound exercises
- 3-4 targeted exercises for their specific goals
- 5 min cooldown
Each exercise should include clear instructions and form cues.

Example format:
{str(example_format)}

Make sure your responses are less than 1000 words in length.
"""

        
        messages = [
            {"role": "system", "content": workout_generator_prompt}
        ]

        response = await self.client.chat.complete_async(
            model=MISTRAL_MODEL,
            messages=messages,
        )
        logger.info(f"workout_response: {response}")
        
        # Parse the response as JSON
        import json
        try:
            # Clean up the response to ensure it's valid JSON
            response_text = response.choices[0].message.content
            # Remove any markdown code block markers if present
            response_text = response_text.replace('```json', '').replace('```', '').strip()
            workout_plan = json.loads(response_text)
            
            # Ensure the workout plan has the required fields
            if not isinstance(workout_plan, dict):
                raise ValueError("Workout plan must be a dictionary")
            if "exercises" not in workout_plan:
                workout_plan["exercises"] = []
            if "warmup" not in workout_plan:
                workout_plan["warmup"] = "5 minutes light cardio and dynamic stretching"
            if "cooldown" not in workout_plan:
                workout_plan["cooldown"] = "5 minutes stretching"
            
            logger.info(f"Starting workout session")
            self.db.start_workout_session(user_id, workout_plan)
            logger.info(f"Workout plan: {workout_plan}")
            return workout_plan
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse workout plan: {e}")
            # Return a basic workout plan as fallback
            fallback_plan = {
                "warmup": "5 minutes light cardio and dynamic stretching",
                "exercises": [
                    {
                        "name": "Bodyweight Squats",
                        "sets": 3,
                        "reps": "10",
                        "weight": "bodyweight",
                        "form_cues": "Keep chest up, knees tracking over toes"
                    },
                    {
                        "name": "Push-ups",
                        "sets": 3,
                        "reps": "10",
                        "weight": "bodyweight",
                        "form_cues": "Keep core tight, elbows at 45 degrees"
                    }
                ],
                "cooldown": "5 minutes stretching"
            }
            self.db.start_workout_session(user_id, fallback_plan)
            return fallback_plan

    async def evaluate_exercise_performance(
        self, user_id: int, planned_exercise: Dict[str, Any], actual_performance: str
    ) -> str:
        """Evaluate exercise performance and determine progression"""
        user_data = self.db.get_user_data(user_id)
        exercise_name = planned_exercise["name"]
        
        # Get previous performance
        exercise_history = user_data.get("exercise_history", {}).get(exercise_name, [])
        previous_max = max([ex.get("weight", 0) for ex in exercise_history]) if exercise_history else 0
        
        messages = [
            {"role": "system", "content": EXERCISE_EVALUATION_PROMPT.format(
                target_performance=f"{planned_exercise['sets']}x{planned_exercise['reps']} @{planned_exercise['weight']}",
                actual_performance=actual_performance,
                previous_max=previous_max
            )}
        ]
        
        response = await self.client.chat.complete_async(
            model=MISTRAL_MODEL,
            messages=messages,
        )
        
        evaluation = response.choices[0].message.content.strip().lower()
        
        # Update exercise history
        self.db.update_exercise_history(user_id, exercise_name, {
            "planned": planned_exercise,
            "actual": actual_performance,
            "evaluation": evaluation
        })
        
        return evaluation

    async def generate_workout_summary(self, session_results: Dict[str, Any]) -> str:
        """Generate a summary of the workout session"""
        messages = [
            {"role": "system", "content": "You are a supportive fitness coach. Create an encouraging summary of the workout session, highlighting achievements and areas for improvement."},
            {"role": "user", "content": str(session_results)}
        ]
        
        response = await self.client.chat.complete_async(
            model=MISTRAL_MODEL,
            messages=messages,
        )
        
        return response.choices[0].message.content

