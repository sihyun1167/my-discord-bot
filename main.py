import discord
from discord.ext import commands
import json
import os
import re
from flask import Flask
import threading

app = Flask('')

@app.route('/')
def home():
    return "Bot is alive!"

def run_web():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

threading.Thread(target=run_web, daemon=True).start()

# ==========================================
# 1. 봇 기본 설정
# ==========================================
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

DATA_FILE = 'donations.json'
TARGET_CHANNEL_ID = 1550346247506755584

# ------------------------------------------
# [후원 역할 및 이모지 설정]
# (목표 금액, 역할 ID, "대체할 이모지")
# ------------------------------------------
ROLE_CONFIG = [
    (0,      1550681759493132308, "🍇"), # 기본 후원
    (10000,  1550682168911466567, "🍒"), # 1만원 이상
    (50000,  1550681508220506232, "🫐"), # 5만원 이상
    (100000, 1550682372054454415, "🍰")  # 10만원 이상
]

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_data(data):
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

async def update_member_role_and_nickname(member: discord.Member, total_amount: int):
    """누적 금액에 맞춰 역할 부여/제거 및 닉네임 이모지 동적 교체"""
    
    achieved_donation_roles = [] # (역할 객체, 이모지)

    # 1. 금액 조건에 따라 역할 지급 또는 회수(환불 대응)
    for goal_amount, role_id, emoji in ROLE_CONFIG:
        role = member.guild.get_role(role_id)
        if not role:
            continue

        if total_amount >= goal_amount:
            # 기준 금액 이상 -> 역할 지급
            achieved_donation_roles.append((role, emoji))
            if role not in member.roles:
                try:
                    await member.add_roles(role)
                except discord.Forbidden:
                    print(f"권한 오류: {role.name} 역할을 부여할 권한이 없습니다.")
        else:
            # 기준 금액 미만 -> 환불로 인한 역할 박탈
            if role in member.roles:
                try:
                    await member.remove_roles(role)
                except discord.Forbidden:
                    print(f"권한 오류: {role.name} 역할을 제거할 권한이 없습니다.")
# 2. 닉네임 이모지 교체 여부 판단 (기존 역할 vs 후원 역할 높이 비교)
    current_nick = member.display_name
    emoji_pattern = re.compile(
        r'[\U00010000-\U0010ffff]|[\u2600-\u27ff]|[\u2300-\u23ff]',
        flags=re.UNICODE
    )

    if achieved_donation_roles:
        # 달성한 후원 역할 중 가장 높은 위치(position)의 역할 선택
        highest_donation_role, highest_emoji = max(achieved_donation_roles, key=lambda item: item[0].position)

        # 유저가 보유한 '후원 역할 외의 역할' 중 가장 높은 위치의 역할 가져오기
        donation_role_ids = [r_id for _, r_id, _ in ROLE_CONFIG]
        other_roles = [r for r in member.roles if r.id not in donation_role_ids and r != member.guild.default_role]

        # 기존 보유 역할 중 최상위 위치 (기존 역할이 없으면 position은 -1)
        user_highest_other_position = max([r.position for r in other_roles], default=-1)

        # 조건: '후원 역할'이 유저의 '기존 최상위 역할'보다 위치가 높을 때만 적용
        if highest_donation_role.position > user_highest_other_position:
            if emoji_pattern.search(current_nick):
                new_nick = emoji_pattern.sub(highest_emoji, current_nick, count=1)
            else:
                new_nick = f"{highest_emoji} {current_nick}"

            if current_nick != new_nick:
                try:
                    await member.edit(nick=new_nick)
                except discord.Forbidden:
                    print(f"권한 오류: {member.display_name}님의 닉네임을 변경할 권한이 없습니다.")

@bot.event
async def on_ready():
    print(f'{bot.user} 후원 봇이 준비되었습니다!')

# ==========================================
# 2. 후원 추가 명령어 (!후원 @이름 금액)
# ==========================================
@bot.command()
@commands.has_permissions(administrator=True)
async def 후원(ctx, member: discord.Member, amount: int):
    data = load_data()
    user_id = str(member.id)

    if user_id not in data:
        data[user_id] = {'name': member.display_name, 'total': 0}

    data[user_id]['total'] += amount
    data[user_id]['name'] = member.display_name
    save_data(data)

    current_total = data[user_id]['total']

    message_text = (
        f"┈ㆍ{member.mention}\n"
        f"<a:D_A_11:1550376638938611742> ┄。{amount:,}원 후원！ ₊⋆\n"
        f"╰୧ㆍ누적 {current_total:,}원⸝⸝♡"
    )

    target_channel = bot.get_channel(TARGET_CHANNEL_ID)
    send_channel = target_channel if target_channel else ctx

    await send_channel.send(message_text)

    # 역할 및 이모지 업데이트
    await update_member_role_and_nickname(member, current_total)

# ==========================================
# 3. 환불 명령어 (!환불 @이름 금액)
# ==========================================
@bot.command()
@commands.has_permissions(administrator=True)
async def 환불(ctx, member: discord.Member, amount: int):
    data = load_data()
    user_id = str(member.id)

    if user_id not in data or data[user_id]['total'] <= 0:
        await ctx.send(f"{member.display_name}님은 환불 처리할 후원 내역이 없습니다.")
        return

    data[user_id]['total'] = max(0, data[user_id]['total'] - amount)
    data[user_id]['name'] = member.display_name
    save_data(data)

    current_total = data[user_id]['total']

    message_text = (
        f"┈ㆍ{member.mention}\n"
        f"<a:D_A_10:1550376622060736552>┄。{amount:,}원 환불╥﹏╥₊⋆\n"
        f"╰୧ㆍ현재 누적 {current_total:,}원⸝⸝♡"
    )

    target_channel = bot.get_channel(TARGET_CHANNEL_ID)
    send_channel = target_channel if target_channel else ctx

    await send_channel.send(message_text)

    # 환불된 금액에 맞춰 역할 회수 및 이모지 강등 처리
    await update_member_role_and_nickname(member, current_total)

# ==========================================
# 4. 봇 실행
# ==========================================
bot.run(os.getenv('TOKEN'))
