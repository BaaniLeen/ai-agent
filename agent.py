import os
from mistralai import Mistral
import discord
from datetime import datetime, timedelta
import logging
from database import Database

MISTRAL_MODEL = "mistral-large-latest"
SYSTEM_PROMPT = """You are a compassionate life coach. Help users build habits by:
1. Setting clear milestones based on their goals
2. Tracking daily progress and celebrating streaks
3. Providing encouragement with self-compassion when they face challenges
4. Celebrating their wins, no matter how small
5. Helping users overcome obstacles by understanding their challenges
Make sure your responses are less than 2000 words in length."""

ONBOARDING_PROMPT = "Welcome! I'm your personal habit coach. What habit would you like to build? Please share your specific goals and what motivates you. Also, what time would you like me to check in with you daily? (e.g., '9:00 AM')"

REMINDER_MESSAGE = "Hey! 👋 I noticed you haven't checked in about your habit today. How did it go with {habit_goal}? Remember, I'm here to support you, not judge. Even small progress is worth celebrating! 🌟"

STREAK_MILESTONES = {
    3: "🌱 3-day streak! You're building momentum!",
    7: "🌟 One week streak! You're making this a part of your routine!",
    14: "🔥 Two week streak! Your commitment is inspiring!",
    21: "💫 21 days! You're well on your way to making this a lasting habit!",
    30: "🏆 30-day streak! What an amazing achievement!",
}

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
        if not user_data or not user_data["onboarded"]:
            return False
            
        last_check_in = datetime.strptime(user_data["last_check_in"], "%Y-%m-%d")
        reminder_time = datetime.strptime(user_data["reminder_time"], "%H:%M").time()
        current_time = datetime.now()
        
        logger.info(f"last_check_in: {last_check_in}; reminder_time: {reminder_time}; current_time:{current_time}")
        # If it's past reminder time and user hasn't checked in today
        return (current_time.time() > reminder_time and 
                last_check_in.date() < current_time.date())


    async def send_reminder(self, user_id, channel):
        """Send a reminder message to the user"""
        logger.info(f"Sending reminder for user: {user_id} to channel: {channel}")
        user_data = self.db.get_user_data(user_id)
        habit_goal = user_data["habit_goal"]
        reminder = REMINDER_MESSAGE.format(habit_goal=habit_goal)
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
            return ONBOARDING_PROMPT
        
        # Add message to conversation history
        message_entry = {
            "role": "user",
            "content": message.content,
            "date": current_date
        }
        self.db.update_conversation_history(user_id, message_entry)
        
        # Handle onboarding
        if not user_data["onboarded"]:
            # Extract reminder time from the message if provided
            message_lower = message.content.lower()
            if "am" in message_lower or "pm" in message_lower:
                try:
                    time_str = message_lower.split("at ")[-1].split(" ")[0]
                    reminder_time = datetime.strptime(time_str, "%H:%M").strftime("%H:%M")
                    self.db.update_user_data(user_id, {"reminder_time": reminder_time})
                except:
                    pass
            
            # Update user data for onboarding
            self.db.update_user_data(user_id, {
                "habit_goal": message.content,
                "onboarded": True
            })
            
            # Get milestones
            milestone_prompt = f"Based on the user's habit goal: '{message.content}', suggest 3 achievable milestones. Format as a list."
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
            
            response = f"Thank you for sharing! I've noted your habit goal:\n\n'{message.content}'\n\nHere are some milestones we can work toward:\n\n{milestones}\n\nI'll check in with you daily at {user_data['reminder_time']} to track your progress. Remember, building habits takes time and self-compassion is key. How did you do with your habit today?"
            
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
            {"role": "system", "content": f"User's habit goal: {user_data['habit_goal']}"},
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
            messages.append({"role": "system", "content": "This is a new day. Ask about progress on their habit and provide encouragement. If they completed their habit, celebrate. If not, show understanding and help identify obstacles."})
            self.db.update_user_data(user_id, {"last_check_in": current_date})
        
        response = await self.client.chat.complete_async(
            model=MISTRAL_MODEL,
            messages=messages,
        )
        
        response_message = response.choices[0].message.content
        
        # Update streak if the message indicates completion
        # This is a simple check - you might want to make it more sophisticated
        message_lower = message.content.lower()
        if "yes" in message_lower or "done" in message_lower or "completed" in message_lower:
            streak_milestone = self.update_streak(user_id, completed=True)
            if streak_milestone:
                response_message = f"{response_message}\n\n{streak_milestone}"
        elif "no" in message_lower or "didn't" in message_lower or "failed" in message_lower:
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
