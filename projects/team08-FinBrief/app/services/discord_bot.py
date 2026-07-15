"""FinBrief 관리 챗봇 (Discord 슬래시 커맨드 엔트리포인트).
   실행:  python -m app.services.discord_bot
   로직은 chatbot.handle + SubscriptionService 재사용(얇은 엔트리포인트)."""
from __future__ import annotations

import asyncio
import os

import discord
from discord import app_commands

from app.core.env import load_dotenv
from app.services import chatbot
from app.services.chatbot import handle
from app.services.subscription_service import SubscriptionService
from app.repositories.memory import create_memory_repositories      # 로컬 개발용(재시작 시 초기화)
from app.repositories.supabase import create_supabase_repositories  # 실 DB(영속)


load_dotenv()

# repo 번들: SUPABASE_URL 있으면 실 DB(영속), 없으면 memory(재시작 시 초기화).
# 봇은 news.match 를 안 쓰므로 query_embedding_provider 불필요.
_REPOS = None


def _repos():
    global _REPOS
    if _REPOS is None:
        if os.getenv("SUPABASE_URL"):
            _REPOS = create_supabase_repositories()
        else:
            _REPOS = create_memory_repositories()
    return _REPOS


def _service() -> SubscriptionService:
    return SubscriptionService(_repos())


_gid = os.getenv("DISCORD_GUILD_ID")
GUILD = discord.Object(id=int(_gid)) if _gid else None   # 설정 시 테스트 서버 즉시 반영용

intents = discord.Intents.default()
intents.message_content = True        # @멘션/DM 대화형 메시지 내용 수신(포털에서도 ON 필요)
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)


@tree.command(name="finbrief", description="브리핑 메이트에게 관심 금융 토픽을 자연어로 관리합니다.")
@app_commands.describe(message='예 : `나스닥 구독해줘`, `내 토픽 보여줘`, `비트코인 취소해줘`, `리포트 설명해줘`, `출처 설명해줘`, `티어 확인해줘`')
async def finbrief(interaction: discord.Interaction, message: str):
    # LLM intent 파싱이 3초를 넘길 수 있어 먼저 defer(15분 확보), 블로킹 handle 은 스레드에서.
    await interaction.response.defer(ephemeral=True)  # "생각 중…" (본인만 보이게)
    res = await asyncio.to_thread(handle, _service(), "discord", str(interaction.user.id), message,
                                  str(interaction.channel_id))  # 구독 시 이 채널로 카드 발송
    await interaction.followup.send(res["reply"], ephemeral=True)


@client.event
async def on_ready():
    if GUILD is not None:                    # 개발용 테스트 서버: 즉시 반영
        tree.copy_global_to(guild=GUILD)     # 전역 커맨드를 테스트 길드에 복사
        await tree.sync(guild=GUILD)
    await tree.sync()                        # 전역 등록 → 봇이 들어간 모든 서버(전파 최대 ~1시간)
    print(f"✅ logged in as {client.user}")


@client.event
async def on_message(message: discord.Message):
    # 슬래시(/finbrief)는 그대로 두고 @멘션/DM 대화형을 병행. 노이즈·프라이버시로 멘션/DM만 반응.
    if message.author.bot:
        return
    is_dm = message.guild is None
    mentioned = client.user in message.mentions
    if not (is_dm or mentioned):
        return
    text = message.content
    for tok in (f"<@{client.user.id}>", f"<@!{client.user.id}>"):
        text = text.replace(tok, "")
    text = text.strip()
    async with message.channel.typing():     # LLM 파싱 지연 동안 "입력 중…"
        res = await asyncio.to_thread(handle, _service(), "discord",
                                      str(message.author.id), text, str(message.channel.id))
    await message.reply(res["reply"], mention_author=False)


@client.event
async def on_guild_join(guild: discord.Guild):
    # 서버 초대되면 사용법 자동 안내(첫 등록 마찰 완화). 발송 권한 없으면 조용히 skip.
    ch = guild.system_channel or next(
        (c for c in guild.text_channels if c.permissions_for(guild.me).send_messages), None)
    if ch:
        await ch.send(chatbot.welcome_text(_service()))


if __name__ == "__main__":
    client.run(os.environ["DISCORD_BOT_TOKEN"])
