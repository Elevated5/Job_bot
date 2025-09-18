import os
import json
import asyncio
import datetime
from typing import Dict, Any, Optional, List

import discord
from discord.ext import commands

# ------------- CONFIG: FILL THESE -------------
TOKEN = "MTQxMzI0Mzc2NjA4ODc5NDIxNA.G_Adv1.cjkkimE7knPqJbl_4eIg6FQhPJBffI3PLStEew"

GUILD_ID = 0  # Optional safety; set to your guild/server ID or leave 0 to work on any guild

# CHANNELS
JOB_BOARD_CHANNEL_ID = 1413240419608825958      # Channel where the combined buttons will live (persistent)
JOB_REVIEW_CHANNEL_ID = 1413240960405475348       # Private mods-only review channel
JOB_LISTINGS_CHANNEL_ID = 1373916906775380058    # Public channel where approved jobs get posted (FORUM CHANNEL)
SERVICES_LISTINGS_CHANNEL_ID = 1373916692601896961  # Channel where service listings are posted (FORUM CHANNEL)

# ROLES / CATEGORY
MODS_ROLE_ID = 1373910447559802931             # Role ID for moderators
PRIVATE_DISCUSS_CATEGORY_ID = 0 # Category ID where private applicant chats are created (optional; set 0 to use no category)

# BUMP COOLDOWN
BUMP_COOLDOWN_SECS = 3 * 60 * 60  # 3 hours

# DATA FILE
DATA_FILE = "data.json"

# PAYMENT METHODS (customize as needed)
PAYMENT_METHODS = [
    "PayPal",
    "Bank Transfer",
    "Wise",
    "Cryptocurrency",
    "Upwork",
    "Freelancer.com",
    "Other"
]

# FREELANCER DETAILS (customize as needed)
FREELANCER_DETAILS = [
    "Experience Level (Junior/Mid/Senior)",
    "Portfolio Link",
    "Previous Work Examples",
    "Specific Skills/Tools",
    "Availability (Hours per week)",
    "Timezone/Region"
]
# ----------------------------------------------

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.message_content = True  # Required for component interactions

bot = commands.Bot(command_prefix="!", intents=intents)

# ---------- Persistence ----------
data_lock = asyncio.Lock()
data: Dict[str, Any] = {
    "counters": {"job": 0, "service": 0},
    "jobs": {},        # job_id -> job dict
    "services": {},    # service_id -> service dict
}

def now_utc() -> str:
    return datetime.datetime.utcnow().isoformat()

def parse_utc(ts: Optional[str]) -> Optional[datetime.datetime]:
    if not ts:
        return None
    return datetime.datetime.fromisoformat(ts)

async def save_data():
    async with data_lock:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

async def load_data():
    global data
    if os.path.exists(DATA_FILE):
        async with data_lock:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)

def next_id(kind: str) -> int:
    data["counters"][kind] += 1
    return data["counters"][kind]

# ---------- Helpers ----------
def is_mod(member: discord.Member) -> bool:
    if MODS_ROLE_ID == 0:
        # If no mod role configured, fallback to Manage Guild permission
        return member.guild_permissions.manage_guild
    role = member.guild.get_role(MODS_ROLE_ID)
    return role in member.roles if role else member.guild_permissions.manage_guild

def fmt_user(user_id: int) -> str:
    return f"<@{user_id}>"

def job_embed(job: Dict[str, Any]) -> discord.Embed:
    e = discord.Embed(
        title=f"#{job['id']} • {job['title']}",
        description=job["description"],
        timestamp=parse_utc(job["created_at"]),
        color=discord.Color.blue() if job["status"] == "approved" else discord.Color.orange(),
    )
    e.add_field(name="Budget", value=job["budget"], inline=True)
    e.add_field(name="Timeline", value=job.get("timeline", "Not specified"), inline=True)
    e.add_field(name="Status", value=job["status"].capitalize(), inline=True)
    e.add_field(name="Payment Methods", value=", ".join(job.get("payment_methods", [])), inline=False)
    e.add_field(name="Poster", value=fmt_user(job["poster_id"]), inline=True)
    
    if job.get("freelancer_details"):
        e.add_field(name="Freelancer Requirements", value=job["freelancer_details"], inline=False)
    
    if job.get("last_bump"):
        last_bump = parse_utc(job["last_bump"])
        if last_bump:
            e.add_field(name="Last Bump (UTC)", value=last_bump.strftime("%Y-%m-%d %H:%M"), inline=True)
    return e

def service_embed(svc: Dict[str, Any]) -> discord.Embed:
    e = discord.Embed(
        title=f"#{svc['id']} • {svc['role']} • {fmt_user(svc['user_name'])}",
        description=svc["details"],
        timestamp=parse_utc(svc["created_at"]),
        color=discord.Color.green() if svc.get("status") == "approved" else discord.Color.orange(),
    )
    e.add_field(name="Expected Pay", value=svc["expected_pay"], inline=True)
    e.add_field(name="Payment Methods", value=", ".join(svc.get("payment_methods", [])), inline=False)
    e.add_field(name="Status", value=svc["status"].capitalize(), inline=True)
    
    if svc.get("freelancer_details"):
        e.add_field(name="Freelancer Details", value=svc["freelancer_details"], inline=False)
    
    if svc.get("last_bump"):
        last_bump = parse_utc(svc["last_bump"])
        if last_bump:
            e.add_field(name="Last Bump (UTC)", value=last_bump.strftime("%Y-%m-%d %H:%M"), inline=True)
    return e

async def get_channel(guild: discord.Guild, chan_id: int) -> Optional[discord.abc.GuildChannel]:
    try:
        channel = guild.get_channel(chan_id)
        if channel is None:
            channel = await bot.fetch_channel(chan_id)
        print(f"Fetched channel: {channel.name} (ID: {chan_id}, Type: {type(channel).__name__})")
        return channel
    except discord.NotFound:
        print(f"Channel not found: {chan_id}")
        return None
    except discord.Forbidden:
        print(f"No permission to access channel: {chan_id}")
        return None
    except Exception as e:
        print(f"Error fetching channel {chan_id}: {e}")
        return None

async def ensure_category(guild: discord.Guild) -> Optional[discord.CategoryChannel]:
    if PRIVATE_DISCUSS_CATEGORY_ID:
        cat = guild.get_channel(PRIVATE_DISCUSS_CATEGORY_ID)
        if isinstance(cat, discord.CategoryChannel):
            return cat
    return None  # no category

# ---------- Combined Persistent Buttons ----------
class CombinedBoardView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Create Job Post", style=discord.ButtonStyle.green, custom_id="combined:job")
    async def create_job(self, inter: discord.Interaction, button: discord.ui.Button):
        print(f"Job create button clicked by {inter.user}")
        try:
            await inter.response.send_modal(JobCreateModal())
            print("Modal sent successfully")
        except Exception as e:
            print(f"Error sending modal: {e}")
            await inter.response.send_message("There was an error creating the job form. Please try again.", ephemeral=True)

    @discord.ui.button(label="List Your Service", style=discord.ButtonStyle.blurple, custom_id="combined:service")
    async def create_service(self, inter: discord.Interaction, button: discord.ui.Button):
        print(f"Service create button clicked by {inter.user}")
        try:
            await inter.response.send_modal(ServiceCreateModal())
            print("Service modal sent successfully")
        except Exception as e:
            print(f"Error sending service modal: {e}")
            await inter.response.send_message("There was an error creating the service form. Please try again.", ephemeral=True)

# ---------- Payment Method Selector ----------
class PaymentMethodSelect(discord.ui.Select):
    def __init__(self, placeholder: str = "Select payment methods..."):
        options = [
            discord.SelectOption(label=method, value=method) 
            for method in PAYMENT_METHODS
        ]
        super().__init__(
            placeholder=placeholder,
            min_values=1,
            max_values=len(PAYMENT_METHODS),
            options=options,
            custom_id="payment_methods"
        )

    async def callback(self, inter: discord.Interaction):
        # This will be handled in the modal
        await inter.response.defer()

# ---------- Freelancer Details Selector ----------
class FreelancerDetailsSelect(discord.ui.Select):
    def __init__(self, is_service: bool = False):
        placeholder = "Select freelancer details to include..." if is_service else "Select required freelancer details..."
        options = [
            discord.SelectOption(label=detail, value=detail) 
            for detail in FREELANCER_DETAILS
        ]
        super().__init__(
            placeholder=placeholder,
            min_values=0,
            max_values=len(FREELANCER_DETAILS),
            options=options,
            custom_id="freelancer_details"
        )

    async def callback(self, inter: discord.Interaction):
        # This will be handled in the modal
        await inter.response.defer()

# ---------- Modals ----------
class JobCreateModal(discord.ui.Modal, title="Create Job Post"):
    def __init__(self):
        super().__init__()
        self.title_in = discord.ui.TextInput(label="Job Title",placeholder="Web Developer Needed!", max_length=120)
        self.budget_in = discord.ui.TextInput(label="Budget", placeholder="$500 / $250 / hourly", max_length=60)
        self.timeline_in = discord.ui.TextInput(label="Timeline", placeholder="e.g., 2 weeks, 1 month, ASAP", max_length=60, required=False)
        self.desc_in = discord.ui.TextInput(label="Description", style=discord.TextStyle.paragraph, max_length=2000)
        self.freelancer_custom_in = discord.ui.TextInput(
            label="Additional Freelancer Requirements", 
            style=discord.TextStyle.paragraph, 
            max_length=1000, 
            required=False,
            placeholder="Any specific requirements not covered above"
        )
        
        self.add_item(self.title_in)
        self.add_item(self.budget_in)
        self.add_item(self.timeline_in)
        self.add_item(self.desc_in)
        self.add_item(self.freelancer_custom_in)
        
        # Add payment method selection
        self.payment_view = discord.ui.View(timeout=None)
        self.payment_view.add_item(PaymentMethodSelect())
        
        # Add freelancer details selection
        self.freelancer_view = discord.ui.View(timeout=None)
        self.freelancer_view.add_item(FreelancerDetailsSelect(is_service=False))

    async def on_submit(self, inter: discord.Interaction):
        print("Job form submitted")
        try:
            # Get selected payment methods
            payment_methods = []
            for child in self.payment_view.children:
                if isinstance(child, PaymentMethodSelect):
                    payment_methods = child.values
                    break
            
            # Get selected freelancer details
            freelancer_details_selected = []
            for child in self.freelancer_view.children:
                if isinstance(child, FreelancerDetailsSelect):
                    freelancer_details_selected = child.values
                    break
            
            # Combine selected details with custom input
            freelancer_details = ""
            if freelancer_details_selected:
                freelancer_details += "• " + "\n• ".join(freelancer_details_selected)
            
            custom_details = str(self.freelancer_custom_in).strip()
            if custom_details:
                if freelancer_details:
                    freelancer_details += "\n\n"
                freelancer_details += custom_details

            poster_id = inter.user.id
            async with data_lock:
                job_id = next_id("job")
                job = {
                    "id": job_id,
                    "poster_id": poster_id,
                    "title": str(self.title_in).strip(),
                    "budget": str(self.budget_in).strip(),
                    "timeline": str(self.timeline_in).strip() or "Not specified",
                    "description": str(self.desc_in).strip(),
                    "payment_methods": payment_methods,
                    "freelancer_details": freelancer_details,
                    "status": "pending",
                    "created_at": now_utc(),
                    "last_bump": None,
                    "review_msg_id": None,
                    "listing_msg_id": None,
                    "thread_id": None,
                }
                data["jobs"][str(job_id)] = job
            await save_data()

            # Post to mod review channel
            guild = inter.guild
            if guild is None:
                await inter.response.send_message("This must be used in a server.", ephemeral=True)
                return
                
            review_chan = await get_channel(guild, JOB_REVIEW_CHANNEL_ID)
            if not isinstance(review_chan, (discord.TextChannel, discord.Thread)):
                await inter.response.send_message("Review channel not configured.", ephemeral=True)
                return

            view = ModReviewView(job_id=job_id)
            msg = await review_chan.send(embed=job_embed(job), view=view)
            async with data_lock:
                data["jobs"][str(job_id)]["review_msg_id"] = msg.id
            await save_data()

            await inter.response.send_message("✅ Submitted for mod review.", ephemeral=True)
            print("Job submitted successfully")
            
        except Exception as e:
            print(f"Error in job submission: {e}")
            await inter.response.send_message("There was an error submitting your job. Please try again.", ephemeral=True)

    async def on_error(self, inter: discord.Interaction, error: Exception):
        print(f"Error in JobCreateModal: {error}")
        await inter.response.send_message("There was an error processing your job submission. Please try again.", ephemeral=True)

    async def interaction_check(self, inter: discord.Interaction):
        # Allow the select menus to work
        return True

class JobEditModal(discord.ui.Modal, title="Edit Job Post"):
    def __init__(self, job_id: int, old_title: str, old_budget: str, old_timeline: str, old_desc: str, old_payment_methods: List[str], old_freelancer_details: str):
        super().__init__()
        self.job_id = job_id
        self.title_in = discord.ui.TextInput(label="Job Title", default=old_title, max_length=120)
        self.budget_in = discord.ui.TextInput(label="Budget", default=old_budget, max_length=60)
        self.timeline_in = discord.ui.TextInput(label="Timeline", default=old_timeline, max_length=60, required=False)
        self.desc_in = discord.ui.TextInput(label="Description", default=old_desc, style=discord.TextStyle.paragraph, max_length=2000)
        self.freelancer_custom_in = discord.ui.TextInput(
            label="Additional Freelancer Requirements", 
            style=discord.TextStyle.paragraph, 
            max_length=1000, 
            required=False,
            default=old_freelancer_details or "",
            placeholder="Any specific requirements not covered above"
)
        
        self.add_item(self.title_in)
        self.add_item(self.budget_in)
        self.add_item(self.timeline_in)
        self.add_item(self.desc_in)
        self.add_item(self.freelancer_custom_in)
        
        # Store old values for select menus
        self.old_payment_methods = old_payment_methods
        self.old_freelancer_details = old_freelancer_details
        
        # Add payment method selection
        self.payment_view = discord.ui.View(timeout=None)
        payment_select = PaymentMethodSelect()
        # Set default values
        for option in payment_select.options:
            if option.value in old_payment_methods:
                option.default = True
        self.payment_view.add_item(payment_select)
        
        # Add freelancer details selection
        self.freelancer_view = discord.ui.View(timeout=None)
        freelancer_select = FreelancerDetailsSelect(is_service=False)
        # Extract selected details from the old text (this is a bit hacky)
        selected_details = []
        if old_freelancer_details:
            for detail in FREELANCER_DETAILS:
                if detail in old_freelancer_details:
                    selected_details.append(detail)
        for option in freelancer_select.options:
            if option.value in selected_details:
                option.default = True
        self.freelancer_view.add_item(freelancer_select)

    async def on_submit(self, inter: discord.Interaction):
        jid = str(self.job_id)
        async with data_lock:
            job = data["jobs"].get(jid)
            if not job:
                await inter.response.send_message("Job not found.", ephemeral=True)
                return
            if job["poster_id"] != inter.user.id:
                await inter.response.send_message("You are not the poster of this job.", ephemeral=True)
                return
            
            # Get selected payment methods
            payment_methods = []
            for child in self.payment_view.children:
                if isinstance(child, PaymentMethodSelect):
                    payment_methods = child.values
                    break
            
            # Get selected freelancer details
            freelancer_details_selected = []
            for child in self.freelancer_view.children:
                if isinstance(child, FreelancerDetailsSelect):
                    freelancer_details_selected = child.values
                    break
            
            # Combine selected details with custom input
            freelancer_details = ""
            if freelancer_details_selected:
                freelancer_details += "• " + "\n• ".join(freelancer_details_selected)
            
            custom_details = str(self.freelancer_custom_in).strip()
            if custom_details:
                if freelancer_details:
                    freelancer_details += "\n\n"
                freelancer_details += custom_details

            # Update and send back to pending
            job["title"] = str(self.title_in).strip()
            job["budget"] = str(self.budget_in).strip()
            job["timeline"] = str(self.timeline_in).strip() or "Not specified"
            job["description"] = str(self.desc_in).strip()
            job["payment_methods"] = payment_methods
            job["freelancer_details"] = freelancer_details
            job["status"] = "pending"
            job["last_bump"] = job["last_bump"]  # unchanged
        await save_data()

        # Re-post to review channel (new review message)
        guild = inter.guild
        review_chan = await get_channel(guild, JOB_REVIEW_CHANNEL_ID)
        if isinstance(review_chan, (discord.TextChannel, discord.Thread)):
            msg = await review_chan.send(embed=job_embed(job), view=ModReviewView(job_id=self.job_id))
            async with data_lock:
                data["jobs"][jid]["review_msg_id"] = msg.id
        await save_data()

        # If it was previously listed, mark listing as outdated (optional delete)
        # (We leave the old post up until approved again; mods can decide.)
        await inter.response.send_message("📝 Updated and sent for mod review again.", ephemeral=True)

class ServiceCreateModal(discord.ui.Modal, title="List Your Service"):
    def __init__(self):
        super().__init__()
        self.role_in = discord.ui.TextInput(label="Your Role", max_length=120)
        self.pay_in = discord.ui.TextInput(label="Expected Pay", max_length=60)
        self.details_in = discord.ui.TextInput(label="Payment Method", max_length= 60)
        self.freelancer_custom_in = discord.ui.TextInput(
            label="Skills / Details", 
            style=discord.TextStyle.paragraph, 
            max_length=2000, 
            required=False,
            placeholder="Any information about your skills or experience"
        )
        
        self.add_item(self.role_in)
        self.add_item(self.pay_in)
        self.add_item(self.details_in)
        self.add_item(self.freelancer_custom_in)
        
        # Add payment method selection
        self.payment_view = discord.ui.View(timeout=None)
        self.payment_view.add_item(PaymentMethodSelect())
        
        # Add freelancer details selection
        self.freelancer_view = discord.ui.View(timeout=None)
        self.freelancer_view.add_item(FreelancerDetailsSelect(is_service=True))

    async def on_submit(self, inter: discord.Interaction):
        print("Service form submitted")
        try:
            # Get selected payment methods
            payment_methods = []
            for child in self.payment_view.children:
                if isinstance(child, PaymentMethodSelect):
                    payment_methods = child.values
                    break
            
            # Get selected freelancer details
            freelancer_details_selected = []
            for child in self.freelancer_view.children:
                if isinstance(child, FreelancerDetailsSelect):
                    freelancer_details_selected = child.values
                    break
            
            # Combine selected details with custom input
            freelancer_details = ""
            if freelancer_details_selected:
                freelancer_details += "• " + "\n• ".join(freelancer_details_selected)
            
            custom_details = str(self.freelancer_custom_in).strip()
            if custom_details:
                if freelancer_details:
                    freelancer_details += "\n\n"
                freelancer_details += custom_details

            async with data_lock:
                sid = next_id("service")
                svc = {
                    "id": sid,
                    "user_id": inter.user.id,
                    "user_name": inter.user.display_name,
                    "role": str(self.role_in).strip(),
                    "expected_pay": str(self.pay_in).strip(),
                    "details": str(self.details_in).strip(),
                    "payment_methods": payment_methods,
                    "freelancer_details": freelancer_details,
                    "status": "pending",  # Added status field for moderation
                    "created_at": now_utc(),
                    "last_bump": None,
                    "review_msg_id": None,  # Added for moderation
                    "listing_msg_id": None,
                    "thread_id": None,
                }
                data["services"][str(sid)] = svc
            await save_data()

            # Post to mod review channel (same as jobs)
            guild = inter.guild
            if guild is None:
                await inter.response.send_message("This must be used in a server.", ephemeral=True)
                return
                
            review_chan = await get_channel(guild, JOB_REVIEW_CHANNEL_ID)
            if not isinstance(review_chan, (discord.TextChannel, discord.Thread)):
                await inter.response.send_message("Review channel not configured.", ephemeral=True)
                return

            view = ServiceModReviewView(service_id=sid)
            msg = await review_chan.send(embed=service_embed(svc), view=view)
            async with data_lock:
                data["services"][str(sid)]["review_msg_id"] = msg.id
            await save_data()

            await inter.response.send_message("✅ Submitted for mod review.", ephemeral=True)
            print("Service submitted for review successfully")
            
        except Exception as e:
            print(f"Error in service submission: {e}")
            await inter.response.send_message("There was an error submitting your service. Please try again.", ephemeral=True)

class ServiceEditModal(discord.ui.Modal, title="Edit Service Post"):
    def __init__(self, service_id: int, old_role: str, old_pay: str, old_details: str, old_payment_methods: List[str], old_freelancer_details: str):
        super().__init__()
        self.service_id = service_id
        self.role_in = discord.ui.TextInput(label="Your Role", default=old_role, max_length=120)
        self.pay_in = discord.ui.TextInput(label="Expected Pay", default=old_pay, max_length=60)
        self.details_in = discord.ui.TextInput(label="Skills / Details", default=old_details, style=discord.TextStyle.paragraph, max_length=2000)
        self.freelancer_custom_in = discord.ui.TextInput(
            label="Additional Details About Yourself", 
            style=discord.TextStyle.paragraph, 
            max_length=1000, 
            required=False,
            default=old_freelancer_details or "",
            placeholder="Any additional information about your skills or experience"
        )
        
        self.add_item(self.role_in)
        self.add_item(self.pay_in)
        self.add_item(self.details_in)
        self.add_item(self.freelancer_custom_in)
        
        # Store old values for select menus
        self.old_payment_methods = old_payment_methods
        self.old_freelancer_details = old_freelancer_details
        
        # Add payment method selection
        self.payment_view = discord.ui.View(timeout=None)
        payment_select = PaymentMethodSelect()
        # Set default values
        for option in payment_select.options:
            if option.value in old_payment_methods:
                option.default = True
        self.payment_view.add_item(payment_select)
        
        # Add freelancer details selection
        self.freelancer_view = discord.ui.View(timeout=None)
        freelancer_select = FreelancerDetailsSelect(is_service=True)
        # Extract selected details from the old text (this is a bit hacky)
        selected_details = []
        if old_freelancer_details:
            for detail in FREELANCER_DETAILS:
                if detail in old_freelancer_details:
                    selected_details.append(detail)
        for option in freelancer_select.options:
            if option.value in selected_details:
                option.default = True
        self.freelancer_view.add_item(freelancer_select)

    async def on_submit(self, inter: discord.Interaction):
        sid = str(self.service_id)
        async with data_lock:
            svc = data["services"].get(sid)
            if not svc:
                await inter.response.send_message("Service not found.", ephemeral=True)
                return
            if svc["user_id"] != inter.user.id:
                await inter.response.send_message("You are not the poster of this service.", ephemeral=True)
                return
            
            # Get selected payment methods
            payment_methods = []
            for child in self.payment_view.children:
                if isinstance(child, PaymentMethodSelect):
                    payment_methods = child.values
                    break
            
            # Get selected freelancer details
            freelancer_details_selected = []
            for child in self.freelancer_view.children:
                if isinstance(child, FreelancerDetailsSelect):
                    freelancer_details_selected = child.values
                    break
            
            # Combine selected details with custom input
            freelancer_details = ""
            if freelancer_details_selected:
                freelancer_details += "• " + "\n• ".join(freelancer_details_selected)
            
            custom_details = str(self.freelancer_custom_in).strip()
            if custom_details:
                if freelancer_details:
                    freelancer_details += "\n\n"
                freelancer_details += custom_details

            # Update and send back to pending
            svc["role"] = str(self.role_in).strip()
            svc["expected_pay"] = str(self.pay_in).strip()
            svc["details"] = str(self.details_in).strip()
            svc["payment_methods"] = payment_methods
            svc["freelancer_details"] = freelancer_details
            svc["status"] = "pending"
            svc["last_bump"] = svc["last_bump"]  # unchanged
        await save_data()

        # Re-post to review channel (new review message)
        guild = inter.guild
        review_chan = await get_channel(guild, JOB_REVIEW_CHANNEL_ID)
        if isinstance(review_chan, (discord.TextChannel, discord.Thread)):
            msg = await review_chan.send(embed=service_embed(svc), view=ServiceModReviewView(service_id=self.service_id))
            async with data_lock:
                data["services"][sid]["review_msg_id"] = msg.id
        await save_data()

        await inter.response.send_message("📝 Updated and sent for mod review again.", ephemeral=True)

# ---------- Review View for Mods ----------
class ModReviewView(discord.ui.View):
    def __init__(self, job_id: int):
        super().__init__(timeout=None)
        self.job_id = job_id

    async def delete_review_message(self, inter: discord.Interaction):
        """Delete the review message after mod action"""
        try:
            jid = str(self.job_id)
            job = data["jobs"].get(jid)
            if job and job.get("review_msg_id"):
                review_chan = await get_channel(inter.guild, JOB_REVIEW_CHANNEL_ID)
                if review_chan:
                    try:
                        msg = await review_chan.fetch_message(job["review_msg_id"])
                        await msg.delete()
                        print(f"Deleted review message for job {self.job_id}")
                    except discord.NotFound:
                        print(f"Review message already deleted for job {self.job_id}")
                    except Exception as e:
                        print(f"Error deleting review message: {e}")
        except Exception as e:
            print(f"Error in delete_review_message: {e}")

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.success, custom_id="review:approve")
    async def approve(self, inter: discord.Interaction, button: discord.ui.Button):
        print(f"Approve button clicked for job {self.job_id}")
        if not is_mod(inter.user):
            await inter.response.send_message("You must be a mod to do that.", ephemeral=True)
            return

        jid = str(self.job_id)
        async with data_lock:
            job = data["jobs"].get(jid)
            if not job:
                await inter.response.send_message("Job not found.", ephemeral=True)
                return
            job["status"] = "approved"
        await save_data()

        # Delete the review message first
        await self.delete_review_message(inter)

        # Publish to listings channel (which is a forum)
        guild = inter.guild
        list_chan = await get_channel(guild, JOB_LISTINGS_CHANNEL_ID)
        
        if not isinstance(list_chan, (discord.TextChannel, discord.ForumChannel)):
            error_msg = "Listings channel not configured or accessible."
            print(error_msg)
            # Revert status since we couldn't post
            async with data_lock:
                job["status"] = "pending"
            await save_data()
            await inter.response.send_message(error_msg, ephemeral=True)
            return

        try:
            view = JobPublicView(job_id=self.job_id, poster_id=job["poster_id"])
            embed = job_embed(job)
            
            if isinstance(list_chan, discord.ForumChannel):
                # For forum channels, create a post instead of sending a message
                thread, message = await list_chan.create_thread(
                    name=f"Job #{self.job_id}: {job['title'][:90]}",
                    content="Job posting details:",
                    embed=embed,
                    view=view
                )
                msg_id = message.id
                thread_id = thread.id
            else:
                # For regular text channels
                msg = await list_chan.send(embed=embed, view=view)
                thread = await msg.create_thread(name=f"job-{self.job_id}-{job['title'][:40]}", auto_archive_duration=1440)
                msg_id = msg.id
                thread_id = thread.id

            async with data_lock:
                data["jobs"][jid]["listing_msg_id"] = msg_id
                data["jobs"][jid]["thread_id"] = thread_id
            await save_data()

            # Notify poster
            try:
                user = await bot.fetch_user(job["poster_id"])
                await user.send(f"✅ Your job `#{self.job_id}` has been approved and posted.")
            except Exception as e:
                print(f"Could not notify user: {e}")

            await inter.response.send_message("Approved and posted.", ephemeral=True)
            print(f"Job {self.job_id} approved successfully")
            
        except Exception as e:
            print(f"Error posting job to listings: {e}")
            # Revert status on error
            async with data_lock:
                job["status"] = "pending"
            await save_data()
            await inter.response.send_message(f"Error posting job: {e}", ephemeral=True)

    @discord.ui.button(label="Reject", style=discord.ButtonStyle.danger, custom_id="review:reject")
    async def reject(self, inter: discord.Interaction, button: discord.ui.Button):
        print(f"Reject button clicked for job {self.job_id}")
        if not is_mod(inter.user):
            await inter.response.send_message("You must be a mod to do that.", ephemeral=True)
            return

        jid = str(self.job_id)
        async with data_lock:
            job = data["jobs"].get(jid)
            if not job:
                await inter.response.send_message("Job not found.", ephemeral=True)
                return
            job["status"] = "rejected"
        await save_data()

        # Delete the review message
        await self.delete_review_message(inter)

        # Notify poster
        try:
            user = await bot.fetch_user(job["poster_id"])
            await user.send(f"❌ Your job `#{self.job_id}` was rejected by moderators.")
        except Exception as e:
            print(f"Could not notify user: {e}")

        await inter.response.send_message("Rejected.", ephemeral=True)
        print(f"Job {self.job_id} rejected")

# ---------- Service Review View for Mods ----------
class ServiceModReviewView(discord.ui.View):
    def __init__(self, service_id: int):
        super().__init__(timeout=None)
        self.service_id = service_id

    async def delete_review_message(self, inter: discord.Interaction):
        """Delete the review message after mod action"""
        try:
            sid = str(self.service_id)
            svc = data["services"].get(sid)
            if svc and svc.get("review_msg_id"):
                review_chan = await get_channel(inter.guild, JOB_REVIEW_CHANNEL_ID)
                if review_chan:
                    try:
                        msg = await review_chan.fetch_message(svc["review_msg_id"])
                        await msg.delete()
                        print(f"Deleted review message for service {self.service_id}")
                    except discord.NotFound:
                        print(f"Review message already deleted for service {self.service_id}")
                    except Exception as e:
                        print(f"Error deleting review message: {e}")
        except Exception as e:
            print(f"Error in delete_review_message: {e}")

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.success, custom_id="svc_review:approve")
    async def approve(self, inter: discord.Interaction, button: discord.ui.Button):
        print(f"Approve button clicked for service {self.service_id}")
        if not is_mod(inter.user):
            await inter.response.send_message("You must be a mod to do that.", ephemeral=True)
            return

        sid = str(self.service_id)
        async with data_lock:
            svc = data["services"].get(sid)
            if not svc:
                await inter.response.send_message("Service not found.", ephemeral=True)
                return
            svc["status"] = "approved"
        await save_data()

        # Delete the review message first
        await self.delete_review_message(inter)

        # Publish to services listings channel
        guild = inter.guild
        list_chan = await get_channel(guild, SERVICES_LISTINGS_CHANNEL_ID)
        
        if not isinstance(list_chan, (discord.TextChannel, discord.ForumChannel)):
            error_msg = "Services listings channel not configured or accessible."
            print(error_msg)
            # Revert status since we couldn't post
            async with data_lock:
                svc["status"] = "pending"
            await save_data()
            await inter.response.send_message(error_msg, ephemeral=True)
            return

        try:
            view = ServicePublicView(service_id=self.service_id, poster_id=svc["user_id"])
            embed = service_embed(svc)
            
            if isinstance(list_chan, discord.ForumChannel):
                # For forum channels, create a post instead of sending a message
                thread, message = await list_chan.create_thread(
                    name=f"Service #{self.service_id}: {svc['role'][:90]}",
                    content="Service listing details:",
                    embed=embed,
                    view=view
                )
                msg_id = message.id
                thread_id = thread.id
            else:
                # For regular text channels
                msg = await list_chan.send(embed=embed, view=view)
                thread = await msg.create_thread(name=f"service-{self.service_id}-{svc['role'][:40]}", auto_archive_duration=1440)
                msg_id = msg.id
                thread_id = thread.id

            async with data_lock:
                data["services"][sid]["listing_msg_id"] = msg_id
                data["services"][sid]["thread_id"] = thread_id
            await save_data()

            # Notify poster
            try:
                user = await bot.fetch_user(svc["user_id"])
                await user.send(f"✅ Your service `#{self.service_id}` has been approved and posted.")
            except Exception as e:
                print(f"Could not notify user: {e}")

            await inter.response.send_message("Approved and posted.", ephemeral=True)
            print(f"Service {self.service_id} approved successfully")
            
        except Exception as e:
            print(f"Error posting service to listings: {e}")
            # Revert status on error
            async with data_lock:
                svc["status"] = "pending"
            await save_data()
            await inter.response.send_message(f"Error posting service: {e}", ephemeral=True)

    @discord.ui.button(label="Reject", style=discord.ButtonStyle.danger, custom_id="svc_review:reject")
    async def reject(self, inter: discord.Interaction, button: discord.ui.Button):
        print(f"Reject button clicked for service {self.service_id}")
        if not is_mod(inter.user):
            await inter.response.send_message("You must be a mod to do that.", ephemeral=True)
            return

        sid = str(self.service_id)
        async with data_lock:
            svc = data["services"].get(sid)
            if not svc:
                await inter.response.send_message("Service not found.", ephemeral=True)
                return
            svc["status"] = "rejected"
        await save_data()

        # Delete the review message
        await self.delete_review_message(inter)

        # Notify poster
        try:
            user = await bot.fetch_user(svc["user_id"])
            await user.send(f"❌ Your service `#{self.service_id}` was rejected by moderators.")
        except Exception as e:
            print(f"Could not notify user: {e}")

        await inter.response.send_message("Rejected.", ephemeral=True)
        print(f"Service {self.service_id} rejected")

# ---------- Public Job View (Apply / Bump / Edit / Delete) ----------
class JobPublicView(discord.ui.View):
    def __init__(self, job_id: int, poster_id: int):
        super().__init__(timeout=None)
        self.job_id = job_id
        self.poster_id = poster_id

    @discord.ui.button(label="Apply", style=discord.ButtonStyle.primary, custom_id="job:apply")
    async def apply(self, inter: discord.Interaction, button: discord.ui.Button):
        print(f"Apply button clicked for job {self.job_id}")
        
        # Get the job data with proper locking
        async with data_lock:
            job = data["jobs"].get(str(self.job_id))
            if not job:
                await inter.response.send_message("Job not found.", ephemeral=True)
                return
            # if job["status"] != "approved":
            #     await inter.response.send_message("This job is not available for application.", ephemeral=True)
            #     return

        guild = inter.guild
        if guild is None:
            await inter.response.send_message("Must be used in a server.", ephemeral=True)
            return

        # Create private discussion channel
        category = await ensure_category(guild)
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True, manage_messages=True),
        }
        
        # Get the poster member
        try:
            poster = guild.get_member(job["poster_id"]) or await guild.fetch_member(job["poster_id"])
            overwrites[poster] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
        except discord.NotFound:
            await inter.response.send_message("The job poster is no longer in this server.", ephemeral=True)
            return
        
        overwrites[inter.user] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)

        mods_role = guild.get_role(MODS_ROLE_ID) if MODS_ROLE_ID else None
        if mods_role:
            overwrites[mods_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)

        name = f"job-{self.job_id}-apply-{inter.user.name}".lower().replace(" ", "-")[:95]
        
        try:
            ch = await guild.create_text_channel(name=name, category=category, overwrites=overwrites)

            await ch.send(
                f"👋 Private discussion for job `#{self.job_id}`.\nPoster: {poster.mention} | Applicant: {inter.user.mention} | Mods present."
            )
            await inter.response.send_message(f"✅ Created private channel: {ch.mention}", ephemeral=True)
            print(f"Private channel created for job {self.job_id}")
            
        except discord.Forbidden:
            await inter.response.send_message("❌ I don't have permission to create channels.", ephemeral=True)
        except Exception as e:
            await inter.response.send_message(f"❌ Error creating channel: {e}", ephemeral=True)
            print(f"Error creating channel: {e}")

    @discord.ui.button(label="Bump", style=discord.ButtonStyle.success, custom_id="job:bump")
    async def bump(self, inter: discord.Interaction, button: discord.ui.Button):
        print(f"Bump button clicked for job {self.job_id}")
        if inter.user.id != self.poster_id and not is_mod(inter.user):
            await inter.response.send_message("Only the poster or mods can bump this post.", ephemeral=True)
            return
        
        jid = str(self.job_id)
        
        # Get the latest job data
        async with data_lock:
            job = data["jobs"].get(jid)
            if not job:
                await inter.response.send_message("Job not found.", ephemeral=True)
                return
            # if job["status"] != "approved":
            #     await inter.response.send_message("Job not available to bump. It must be approved first.", ephemeral=True)
            #     return
            
            last = parse_utc(job.get("last_bump"))
            now = datetime.datetime.utcnow()
            if last and (now - last).total_seconds() < BUMP_COOLDOWN_SECS:
                wait_secs = BUMP_COOLDOWN_SECS - (now - last).total_seconds()
                wait_mins = int(wait_secs // 60)
                wait_hrs = int(wait_mins // 60)
                wait_mins %= 60
                
                if wait_hrs > 0:
                    wait_str = f"{wait_hrs} hours and {wait_mins} minutes"
                else:
                    wait_str = f"{wait_mins} minutes"
                    
                await inter.response.send_message(f"⏳ You can bump again in ~{wait_str}.", ephemeral=True)
                return

        # Repost into listings, delete old message (if exists)
        guild = inter.guild
        list_chan = await get_channel(guild, JOB_LISTINGS_CHANNEL_ID)
        if not isinstance(list_chan, (discord.TextChannel, discord.ForumChannel)):
            await inter.response.send_message("Listings channel not configured.", ephemeral=True)
            return

        # Refresh job data after lock
        job = data["jobs"][jid]
        view = JobPublicView(job_id=self.job_id, poster_id=self.poster_id)
        embed = job_embed(job)
        
        try:
            if isinstance(list_chan, discord.ForumChannel):
                # For forum channels, create a new post
                thread, new_msg = await list_chan.create_thread(
                    name=f"Job #{self.job_id}: {job['title'][:90]}",
                    content="Job posting details:",
                    embed=embed,
                    view=view
                )
                new_thread = thread
            else:
                # For regular text channels
                new_msg = await list_chan.send(embed=embed, view=view)
                new_thread = await new_msg.create_thread(name=f"job-{self.job_id}-{job['title'][:40]}", auto_archive_duration=1440)

            # Delete old listing message if it exists
            old_listing_msg_id = job.get("listing_msg_id")
            old_thread_id = job.get("thread_id")
            
            if old_listing_msg_id:
                try:
                    if isinstance(list_chan, discord.ForumChannel) and old_thread_id:
                        # For forum channels, delete the thread
                        old_thread = await bot.fetch_channel(old_thread_id)
                        await old_thread.delete()
                        print(f"Deleted old forum thread for job {self.job_id}")
                    elif not isinstance(list_chan, discord.ForumChannel):
                        old_msg = await list_chan.fetch_message(old_listing_msg_id)
                        await old_msg.delete()
                        print(f"Deleted old message for job {self.job_id}")
                except Exception as e:
                    print(f"Error deleting old listing (may already be deleted): {e}")

            # Update job data with new message and thread IDs
            async with data_lock:
                data["jobs"][jid]["listing_msg_id"] = new_msg.id
                data["jobs"][jid]["thread_id"] = new_thread.id
                data["jobs"][jid]["last_bump"] = now_utc()
            await save_data()

            await inter.response.send_message("📢 Bumped! Your job has been refreshed in the listings.", ephemeral=True)
            print(f"Job {self.job_id} bumped successfully")
            
        except Exception as e:
            print(f"Error during bump operation: {e}")
            await inter.response.send_message("❌ Error bumping job. Please try again later.", ephemeral=True)

    @discord.ui.button(label="Edit", style=discord.ButtonStyle.primary, custom_id="job:edit")
    async def edit(self, inter: discord.Interaction, button: discord.ui.Button):
        print(f"Edit button clicked for job {self.job_id}")
        if inter.user.id != self.poster_id and not is_mod(inter.user):
            await inter.response.send_message("Only the poster or mods can edit this post.", ephemeral=True)
            return

        job = data["jobs"].get(str(self.job_id))
        if not job:
            await inter.response.send_message("Job not found.", ephemeral=True)
            return

        await inter.response.send_modal(JobEditModal(
            job_id=self.job_id,
            old_title=job["title"],
            old_budget=job["budget"],
            old_timeline=job.get("timeline", ""),
            old_desc=job["description"],
            old_payment_methods=job.get("payment_methods", []),
            old_freelancer_details=job.get("freelancer_details", "")
        ))

    @discord.ui.button(label="Delete", style=discord.ButtonStyle.danger, custom_id="job:delete")
    async def delete(self, inter: discord.Interaction, button: discord.ui.Button):
        print(f"Delete button clicked for job {self.job_id}")
        if inter.user.id != self.poster_id and not is_mod(inter.user):
            await inter.response.send_message("Only the poster or mods can delete this post.", ephemeral=True)
            return
            
        jid = str(self.job_id)
        async with data_lock:
            job = data["jobs"].get(jid)
            if not job:
                await inter.response.send_message("Job not found.", ephemeral=True)
                return
            job["status"] = "deleted"
        await save_data()

        # Delete listing message & close thread
        guild = inter.guild
        try:
            list_chan = await get_channel(guild, JOB_LISTINGS_CHANNEL_ID)
            if isinstance(list_chan, (discord.TextChannel, discord.ForumChannel)) and data["jobs"][jid].get("listing_msg_id"):
                if isinstance(list_chan, discord.ForumChannel):
                    # For forum channels, delete the thread
                    thread = await bot.fetch_channel(data["jobs"][jid]["thread_id"])
                    await thread.delete()
                else:
                    msg = await list_chan.fetch_message(data["jobs"][jid]["listing_msg_id"])
                    await msg.delete()
        except Exception as e:
            print(f"Error deleting listing: {e}")

        await inter.response.send_message("🗑️ Job deleted.", ephemeral=True)
        print(f"Job {self.job_id} deleted")

# ---------- Public Service View (Apply / Bump / Edit / Delete) ----------
class ServicePublicView(discord.ui.View):
    def __init__(self, service_id: int, poster_id: int):
        super().__init__(timeout=None)
        self.service_id = service_id
        self.poster_id = poster_id

    @discord.ui.button(label="Hire", style=discord.ButtonStyle.primary, custom_id="service:hire")
    async def hire(self, inter: discord.Interaction, button: discord.ui.Button):
        print(f"Hire button clicked for service {self.service_id}")
        
        # Get the service data with proper locking
        async with data_lock:
            svc = data["services"].get(str(self.service_id))
            if not svc:
                await inter.response.send_message("Service not found.", ephemeral=True)
                return
            if svc["status"] != "approved":
                await inter.response.send_message("This service is not available for hiring.", ephemeral=True)
                return

        guild = inter.guild
        if guild is None:
            await inter.response.send_message("Must be used in a server.", ephemeral=True)
            return

        # Create private discussion channel
        category = await ensure_category(guild)
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True, manage_messages=True),
        }
        
        # Get the service provider member
        try:
            provider = guild.get_member(svc["user_id"]) or await guild.fetch_member(svc["user_id"])
            overwrites[provider] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
        except discord.NotFound:
            await inter.response.send_message("The service provider is no longer in this server.", ephemeral=True)
            return
        
        overwrites[inter.user] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)

        mods_role = guild.get_role(MODS_ROLE_ID) if MODS_ROLE_ID else None
        if mods_role:
            overwrites[mods_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)

        name = f"service-{self.service_id}-hire-{inter.user.name}".lower().replace(" ", "-")[:95]
        
        try:
            ch = await guild.create_text_channel(name=name, category=category, overwrites=overwrites)

            await ch.send(
                f"👋 Private discussion for service `#{self.service_id}`.\nProvider: {fmt_user(svc['user_id'])} | Client: {inter.user.mention} | Mods present."
            )
            await inter.response.send_message(f"✅ Created private channel: {ch.mention}", ephemeral=True)
            print(f"Private channel created for service {self.service_id}")
            
        except discord.Forbidden:
            await inter.response.send_message("❌ I don't have permission to create channels.", ephemeral=True)
        except Exception as e:
            await inter.response.send_message(f"❌ Error creating channel: {e}", ephemeral=True)
            print(f"Error creating channel: {e}")

    @discord.ui.button(label="Bump", style=discord.ButtonStyle.success, custom_id="service:bump")
    async def bump(self, inter: discord.Interaction, button: discord.ui.Button):
        print(f"Bump button clicked for service {self.service_id}")
        if inter.user.id != self.poster_id and not is_mod(inter.user):
            await inter.response.send_message("Only the poster or mods can bump this post.", ephemeral=True)
            return
        
        sid = str(self.service_id)
        
        # Get the latest service data
        async with data_lock:
            svc = data["services"].get(sid)
            if not svc:
                await inter.response.send_message("Service not found.", ephemeral=True)
                return
            if svc["status"] != "approved":
                await inter.response.send_message("Service not available to bump. It must be approved first.", ephemeral=True)
                return
            
            last = parse_utc(svc.get("last_bump"))
            now = datetime.datetime.utcnow()
            if last and (now - last).total_seconds() < BUMP_COOLDOWN_SECS:
                wait_secs = BUMP_COOLDOWN_SECS - (now - last).total_seconds()
                wait_mins = int(wait_secs // 60)
                wait_hrs = int(wait_mins // 60)
                wait_mins %= 60
                
                if wait_hrs > 0:
                    wait_str = f"{wait_hrs} hours and {wait_mins} minutes"
                else:
                    wait_str = f"{wait_mins} minutes"
                    
                await inter.response.send_message(f"⏳ You can bump again in ~{wait_str}.", ephemeral=True)
                return

        # Repost into listings, delete old message (if exists)
        guild = inter.guild
        list_chan = await get_channel(guild, SERVICES_LISTINGS_CHANNEL_ID)
        if not isinstance(list_chan, (discord.TextChannel, discord.ForumChannel)):
            await inter.response.send_message("Listings channel not configured.", ephemeral=True)
            return

        # Refresh service data after lock
        svc = data["services"][sid]
        view = ServicePublicView(service_id=self.service_id, poster_id=self.poster_id)
        embed = service_embed(svc)
        
        try:
            if isinstance(list_chan, discord.ForumChannel):
                # For forum channels, create a new post
                thread, new_msg = await list_chan.create_thread(
                    name=f"Service #{self.service_id}: {svc['role'][:90]}",
                    content="Service listing details:",
                    embed=embed,
                    view=view
                )
                new_thread = thread
            else:
                # For regular text channels
                new_msg = await list_chan.send(embed=embed, view=view)
                new_thread = await new_msg.create_thread(name=f"service-{self.service_id}-{svc['role'][:40]}", auto_archive_duration=1440)

            # Delete old listing message if it exists
            old_listing_msg_id = svc.get("listing_msg_id")
            old_thread_id = svc.get("thread_id")
            
            if old_listing_msg_id:
                try:
                    if isinstance(list_chan, discord.ForumChannel) and old_thread_id:
                        # For forum channels, delete the thread
                        old_thread = await bot.fetch_channel(old_thread_id)
                        await old_thread.delete()
                        print(f"Deleted old forum thread for service {self.service_id}")
                    elif not isinstance(list_chan, discord.ForumChannel):
                        old_msg = await list_chan.fetch_message(old_listing_msg_id)
                        await old_msg.delete()
                        print(f"Deleted old message for service {self.service_id}")
                except Exception as e:
                    print(f"Error deleting old listing (may already be deleted): {e}")

            # Update service data with new message and thread IDs
            async with data_lock:
                data["services"][sid]["listing_msg_id"] = new_msg.id
                data["services"][sid]["thread_id"] = new_thread.id
                data["services"][sid]["last_bump"] = now_utc()
            await save_data()

            await inter.response.send_message("📢 Bumped! Your service has been refreshed in the listings.", ephemeral=True)
            print(f"Service {self.service_id} bumped successfully")
            
        except Exception as e:
            print(f"Error during bump operation: {e}")
            await inter.response.send_message("❌ Error bumping service. Please try again later.", ephemeral=True)

    @discord.ui.button(label="Edit", style=discord.ButtonStyle.primary, custom_id="service:edit")
    async def edit(self, inter: discord.Interaction, button: discord.ui.Button):
        print(f"Edit button clicked for service {self.service_id}")
        if inter.user.id != self.poster_id and not is_mod(inter.user):
            await inter.response.send_message("Only the poster or mods can edit this post.", ephemeral=True)
            return

        svc = data["services"].get(str(self.service_id))
        if not svc:
            await inter.response.send_message("Service not found.", ephemeral=True)
            return

        await inter.response.send_modal(ServiceEditModal(
            service_id=self.service_id,
            old_role=svc["role"],
            old_pay=svc["expected_pay"],
            old_details=svc["details"],
            old_payment_methods=svc.get("payment_methods", []),
            old_freelancer_details=svc.get("freelancer_details", "")
        ))

    @discord.ui.button(label="Delete", style=discord.ButtonStyle.danger, custom_id="service:delete")
    async def delete(self, inter: discord.Interaction, button: discord.ui.Button):
        print(f"Delete button clicked for service {self.service_id}")
        if inter.user.id != self.poster_id and not is_mod(inter.user):
            await inter.response.send_message("Only the poster or mods can delete this post.", ephemeral=True)
            return
            
        sid = str(self.service_id)
        async with data_lock:
            svc = data["services"].get(sid)
            if not svc:
                await inter.response.send_message("Service not found.", ephemeral=True)
                return
            svc["status"] = "deleted"
        await save_data()

        # Delete listing message & close thread
        guild = inter.guild
        try:
            list_chan = await get_channel(guild, SERVICES_LISTINGS_CHANNEL_ID)
            if isinstance(list_chan, (discord.TextChannel, discord.ForumChannel)) and data["services"][sid].get("listing_msg_id"):
                if isinstance(list_chan, discord.ForumChannel):
                    # For forum channels, delete the thread
                    thread = await bot.fetch_channel(data["services"][sid]["thread_id"])
                    await thread.delete()
                else:
                    msg = await list_chan.fetch_message(data["services"][sid]["listing_msg_id"])
                    await msg.delete()
        except Exception as e:
            print(f"Error deleting listing: {e}")

        await inter.response.send_message("🗑️ Service deleted.", ephemeral=True)
        print(f"Service {self.service_id} deleted")

# ---------- Bot Events ----------
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} (ID: {bot.user.id})")
    await load_data()

    # Re-register persistent views
    bot.add_view(CombinedBoardView())
    
    # Register review views for each job that might be in review
    for jid, job in list(data.get("jobs", {}).items()):
        if job.get("status") == "pending":
            bot.add_view(ModReviewView(job_id=int(jid)))
    
    # Register review views for each service that might be in review
    for sid, svc in list(data.get("services", {}).items()):
        if svc.get("status") == "pending":
            bot.add_view(ServiceModReviewView(service_id=int(sid)))
    
    # Register public views for each approved job
    for jid, job in list(data.get("jobs", {}).items()):
        if job.get("status") == "approved":
            bot.add_view(JobPublicView(job_id=int(jid), poster_id=job["poster_id"]))
    
    # Register public views for each approved service
    for sid, svc in list(data.get("services", {}).items()):
        if svc.get("status") == "approved":
            bot.add_view(ServicePublicView(service_id=int(sid), poster_id=svc["user_id"]))
    
    print("All views registered")

    # Ensure the combined message exists
    for guild in bot.guilds:
        if GUILD_ID and guild.id != GUILD_ID:
            continue
            
        # Combined board message
        try:
            chan = guild.get_channel(JOB_BOARD_CHANNEL_ID)
            if isinstance(chan, discord.TextChannel):
                # Check if we already posted the message
                found_message = False
                async for message in chan.history(limit=10):
                    if message.author == bot.user and message.components:
                        found_message = True
                        break
                
                if not found_message:
                    # No message found, send a new one
                    await chan.send("Choose an option below:", view=CombinedBoardView())
                    print("Combined board message sent")
        except Exception as e:
            print(f"⚠️ Could not post in combined board channel: {e}")

# ---------- Commands ----------
@bot.command()
@commands.has_permissions(manage_guild=True)
async def jobs(ctx: commands.Context):
    """List counts by status (mods)."""
    counts = {"pending": 0, "approved": 0, "rejected": 0, "deleted": 0}
    for job in data["jobs"].values():
        counts[job["status"]] = counts.get(job["status"], 0) + 1
    await ctx.reply(f"Jobs: {counts}")

@bot.command()
@commands.has_permissions(manage_guild=True)
async def services(ctx: commands.Context):
    """List service counts by status (mods)."""
    counts = {"pending": 0, "approved": 0, "rejected": 0, "deleted": 0}
    for svc in data["services"].values():
        counts[svc["status"]] = counts.get(svc["status"], 0) + 1
    await ctx.reply(f"Services: {counts}")

@bot.command()
@commands.has_permissions(manage_guild=True)
async def setup(ctx: commands.Context):
    """Setup the combined board message"""
    try:
        # Post combined message
        combined_channel = bot.get_channel(JOB_BOARD_CHANNEL_ID)
        if combined_channel:
            await combined_channel.send("Choose an option below:", view=CombinedBoardView())
            await ctx.send("✅ Combined board button posted!")
            
    except Exception as e:
        await ctx.send(f"Error: {e}")

@bot.command()
@commands.has_permissions(manage_guild=True)
async def check_channels(ctx: commands.Context):
    """Check if all channels are accessible"""
    guild = ctx.guild
    
    channels_to_check = {
        "Job Board": JOB_BOARD_CHANNEL_ID,
        "Job Review": JOB_REVIEW_CHANNEL_ID,
        "Job Listings": JOB_LISTINGS_CHANNEL_ID,
        "Services Listings": SERVICES_LISTINGS_CHANNEL_ID
    }
    
    for name, chan_id in channels_to_check.items():
        try:
            channel = await get_channel(guild, chan_id)
            if channel:
                await ctx.send(f"✅ {name}: {channel.mention} (ID: {chan_id}, Type: {type(channel).__name__})")
            else:
                await ctx.send(f"❌ {name}: Channel not found (ID: {chan_id})")
        except Exception as e:
            await ctx.send(f"❌ {name}: Error accessing channel (ID: {chan_id}): {e}")

# ---------- Run ----------
if __name__ == "__main__":
    print("Starting bot...")
    bot.run(TOKEN)