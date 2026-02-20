import asyncio
import aiohttp
import threading
import time
import random
import os
import re
from datetime import datetime
from telebot import TeleBot, types
import queue
import hashlib
from html import escape

# ==================== CẤU HÌNH ====================
OWNER_ID = 7148987608  # ID duy nhất của đại ca

TOKENS = [
    "8256861284:AAFmhGNTNSDA-TstO9-w7zDumNc4dL7R--4",
    "8392052086:AAEGKkUUh7MSUYaKf_lKuID7Q30tmvLFGUU",
    "8498061847:AAG_UNz7DKwYQR1LlRS0oEtjV0jVvOiR5wM",
    "8525478758:AAGO1ducnnanbgEabufi6PGWq7Ubp-xU2lw",
    "8553743076:AAH7N15Iar5NyyqCo6sh_1z939LSFpOZ64k",
    "8380126142:AAFO9UXJjI46g2rYkfz-7qIFuq_blhoFRDk",
    "8537576898:AAEoKMsoxq_0N9BDVJm73xQjNq0yPWN0ozY",
    "8361918043:AAGU_SrlllgUS75zkVYVLUrmJ5hEQMZzlSo",
    "8508344783:AAEtshzXzEssyT0AWfCrYHTISEKXJ3TWRRA",
    "8416084065:AAHkXLh189_2GRIaggz5BjXcMaygUmNSgr4"
]

MAIN_BOT = TeleBot(TOKENS[0])

# ==================== BIẾN TOÀN CỤC ====================
war_messages = []           # war.txt
nhay_messages = []          # nhay.txt (nội dung nhây, thường là 1 câu dài)
spam_active = {}            # {target_type:target: bool} vd: "war:username", "nhay:user_id", "text:text_hash"
stop_flags = {}
total_sent = {}
total_errors = {}
target_chat_id = {}         # Lưu chat_id cho mỗi target (chỉ dùng cho spam)
message_queues = {}          # {target_key: asyncio.Queue}
producer_tasks = {}          # {target_key: task}
lock = threading.Lock()

# Danh sách user bị theo dõi để xoá tin nhắn
watch_users = set()          # lưu user_id (int)
watch_usernames = set()      # lưu username (str) - sẽ resolve thành id khi có tin nhắn

# Auto rename
auto_rename_active = False
rename_thread = None
group_titles = [
    "🔥 ĐỆ NHẤT WAR 🔥",
    "⚡ CƯỜNG DEV GPT ⚡",
    "💀 BOMB TEAM 💀",
    "🚀 SPAM PRO MAX 🚀",
    "🐉 RỒNG LỬA 🐉",
    "👑 QUYỀN LỰC ĐEN 👑",
    "🌪️ BÃO TÁP 🌪️",
    "🦍 KHỈ ĐỘT BIẾN 🦍"
]

# ==================== LOAD FILE ====================
def load_files():
    global war_messages, nhay_messages
    # War
    try:
        if os.path.exists('war.txt'):
            with open('war.txt', 'r', encoding='utf-8') as f:
                war_messages = [line.strip() for line in f.readlines() if line.strip()]
                war_messages = war_messages * 20  # nhân bản
        else:
            war_messages = ["FUCK", "ĐỊT MẸ", "CON CẶC", "NGU HỌC"] * 50
            with open('war.txt', 'w', encoding='utf-8') as f:
                f.write('\n'.join(war_messages[:100]))
        random.shuffle(war_messages)
        print(f"✅ Loaded {len(war_messages)} war messages")
    except Exception as e:
        print(f"❌ Lỗi war.txt: {e}")
        war_messages = ["WAR"] * 1000

    # Nhay
    try:
        if os.path.exists('nhay.txt'):
            with open('nhay.txt', 'r', encoding='utf-8') as f:
                nhay_messages = [line.strip() for line in f.readlines() if line.strip()]
        else:
            nhay_content = """
[ĐÂY LÀ TIN NHẮN NHÂY DÀI]
Địt mẹ mày con chó này, mày nghĩ mày là ai? Bố mày đây này! Thích war không? Vào đây bố cho mày biết thế nào là lễ độ! 
Con cặc nhà mày, tưởng làm trùm lắm à? Gặp bố mày mày chỉ là thằng hề thôi con ạ.
Đừng để bố mày phải điên lên, không ai chịu nổi đâu. War cả ngày cũng được, bố mày có 5 bot spam liên tục, mày cầm cự được bao lâu?
Nhanh tay lên, đừng để bố mày phải nhắc. Cả lũ chúng mày chỉ là lũ súc vật không hơn không kém!
Ăn cứt đi, rác rưởi của xã hội! Bố mày đây, nhớ mặt tao nhé!
            """.strip().split('\n')
            nhay_messages = [line.strip() for line in nhay_content if line.strip()]
            with open('nhay.txt', 'w', encoding='utf-8') as f:
                f.write('\n'.join(nhay_messages))
        print(f"✅ Loaded {len(nhay_messages)} nhay messages")
    except Exception as e:
        print(f"❌ Lỗi nhay.txt: {e}")
        nhay_messages = ["NHẮN NHÂY MẶC ĐỊNH"] * 10

load_files()

# ==================== BOT WORKER (GIỮ NGUYÊN NHƯ CŨ) ====================
class BotWorker:
    def __init__(self, token):
        self.token = token
        self.session = None
        self.base_url = f"https://api.telegram.org/bot{token}"
        self.running = True
        self.tasks = []

    async def init(self):
        self.session = aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(limit=200, force_close=True, ttl_dns_cache=300),
            timeout=aiohttp.ClientTimeout(total=5)
        )

    async def close(self):
        await self.session.close()

    async def send_message(self, chat_id, text, parse_mode='HTML'):
        url = f"{self.base_url}/sendMessage"
        data = {'chat_id': chat_id, 'text': text, 'parse_mode': parse_mode}
        try:
            async with self.session.post(url, data=data) as resp:
                if resp.status == 200:
                    return True
                elif resp.status == 429:
                    # Rotate DC
                    dc = random.randint(1, 5)
                    alt_url = f"https://api{dc}.telegram.org/bot{self.token}/sendMessage"
                    async with self.session.post(alt_url, data=data) as resp2:
                        return resp2.status == 200
                else:
                    return False
        except:
            return False

    async def worker_loop(self, target_key, chat_id):
        queue = message_queues[target_key]
        while spam_active.get(target_key, False) and self.running:
            try:
                msg = await asyncio.wait_for(queue.get(), timeout=0.1)
            except asyncio.TimeoutError:
                continue
            except:
                break

            # Xác định parse mode dựa trên nội dung (nếu có link tg:// thì dùng HTML)
            parse = 'HTML' if 'tg://' in msg else 'HTML'

            success = await self.send_message(chat_id, msg, parse)
            with lock:
                if success:
                    total_sent[target_key] = total_sent.get(target_key, 0) + 1
                else:
                    total_errors[target_key] = total_errors.get(target_key, 0) + 1

            # Điều chỉnh tốc độ
            qsize = queue.qsize()
            if qsize > 50:
                await asyncio.sleep(0.01)
            elif qsize > 20:
                await asyncio.sleep(0.02)
            else:
                await asyncio.sleep(0.05)

        print(f"🛑 Worker {self.token[:8]} dừng {target_key}")

class BotManager:
    def __init__(self, tokens):
        self.tokens = tokens
        self.workers = []
        self.loop = None
        self.thread = None

    def start(self):
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()

    def _run_loop(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._init_workers())
        self.loop.run_forever()

    async def _init_workers(self):
        for token in self.tokens:
            worker = BotWorker(token)
            await worker.init()
            self.workers.append(worker)
        print(f"✅ {len(self.workers)} bot workers sẵn sàng")

    async def stop_all_workers(self):
        for w in self.workers:
            w.running = False
            await w.close()

    # Spam war (sp1, sp3, sp5)
    async def start_spam_war(self, target_key, chat_id, targets_list, use_tag_link=False):
        """targets_list: list of (target_identifier, type) where type: 'username' or 'user_id'"""
        # Tạo queue chung cho tất cả target trong cùng lệnh? Hay mỗi target riêng?
        # Ta sẽ tạo một queue riêng cho mỗi target_key (ví dụ: "war:user1", "war:user2")
        # Nhưng để đơn giản, mỗi lệnh có thể spam nhiều user, ta tạo một target_key tổng?
        # Tuy nhiên để dễ quản lý dừng riêng, nên mỗi user là một target riêng.
        # Trong sp3, mỗi user sẽ có target_key riêng.
        for target in targets_list:
            key = f"war:{target}"
            if spam_active.get(key, False):
                continue  # bỏ qua nếu đã chạy
            spam_active[key] = True
            stop_flags[key] = False
            target_chat_id[key] = chat_id
            total_sent[key] = 0
            total_errors[key] = 0
            message_queues[key] = asyncio.Queue(maxsize=5000)
            # Producer riêng cho mỗi target
            producer = self.loop.create_task(self._producer_war(key, target, use_tag_link))
            producer_tasks[key] = producer
            # Worker tasks cho mỗi bot
            for worker in self.workers:
                task = self.loop.create_task(worker.worker_loop(key, chat_id))
                worker.tasks.append(task)

    # Spam nhay (sp2, sp4, sp6)
    async def start_spam_nhay(self, target_key, chat_id, targets_list, use_tag_link=False):
        for target in targets_list:
            key = f"nhay:{target}"
            if spam_active.get(key, False):
                continue
            spam_active[key] = True
            stop_flags[key] = False
            target_chat_id[key] = chat_id
            total_sent[key] = 0
            total_errors[key] = 0
            message_queues[key] = asyncio.Queue(maxsize=2000)
            producer = self.loop.create_task(self._producer_nhay(key, target, use_tag_link))
            producer_tasks[key] = producer
            for worker in self.workers:
                task = self.loop.create_task(worker.worker_loop(key, chat_id))
                worker.tasks.append(task)

    # Spam text (sp7)
    async def start_spam_text(self, target_key, chat_id, text, count):
        # target_key dạng "text:hash"
        if spam_active.get(target_key, False):
            return
        spam_active[target_key] = True
        stop_flags[target_key] = False
        target_chat_id[target_key] = chat_id
        total_sent[target_key] = 0
        total_errors[target_key] = 0
        message_queues[target_key] = asyncio.Queue(maxsize=count)
        # Đưa text vào queue count lần
        for _ in range(count):
            await message_queues[target_key].put(text)
        # Producer không cần, vì queue đã có sẵn. Nhưng cần cơ chế dừng khi gửi hết? 
        # Ta sẽ tạo một producer ảo để theo dõi và kết thúc khi gửi đủ
        producer = self.loop.create_task(self._producer_text(target_key, count))
        producer_tasks[target_key] = producer
        for worker in self.workers:
            task = self.loop.create_task(worker.worker_loop(target_key, chat_id))
            worker.tasks.append(task)

    async def _producer_war(self, target_key, target, use_tag_link):
        """Producer cho war: tạo message với tag và war ngẫu nhiên"""
        queue = message_queues[target_key]
        while spam_active.get(target_key, False):
            msg = random.choice(war_messages)
            if use_tag_link:
                # Dùng link ẩn tg://user?id=...
                if isinstance(target, int):  # user_id
                    tag = f"<a href=\"tg://user?id={target}\">‌</a>"
                else:  # username
                    # Với username, ta có thể tag bằng @ nhưng để ẩn thì dùng link ẩn với id random?
                    # Cách tốt nhất: dùng link ẩn với id random và mention @username
                    # Nhưng để đúng yêu cầu, sp5 dùng user_id để tag bằng id, còn username vẫn dùng @
                    # Nên ở đây, nếu use_tag_link True và target là int => dùng link, còn string thì vẫn @
                    if isinstance(target, str):
                        tag = f"<a href=\"tg://user?id={random.randint(1000000,9999999)}\">‌</a>@{target}"
                    else:
                        tag = f"<a href=\"tg://user?id={target}\">‌</a>"
            else:
                # Tag bình thường
                if isinstance(target, str):
                    tag = f"@{target}"
                else:
                    tag = f"<a href=\"tg://user?id={target}\">‌</a>"
            full_msg = f"{tag} {msg}"
            try:
                await queue.put(full_msg)
            except asyncio.QueueFull:
                await asyncio.sleep(0.05)
        print(f"📦 Producer war {target_key} dừng")

    async def _producer_nhay(self, target_key, target, use_tag_link):
        """Producer cho nhay: gửi toàn bộ nội dung nhay.txt trong 1 tin nhắn"""
        queue = message_queues[target_key]
        # Gộp tất cả dòng trong nhay_messages thành 1 đoạn văn
        nhay_text = "\n".join(nhay_messages)
        while spam_active.get(target_key, False):
            if use_tag_link:
                if isinstance(target, int):
                    tag = f"<a href=\"tg://user?id={target}\">‌</a>"
                else:
                    if isinstance(target, str):
                        tag = f"<a href=\"tg://user?id={random.randint(1000000,9999999)}\">‌</a>@{target}"
                    else:
                        tag = f"<a href=\"tg://user?id={target}\">‌</a>"
            else:
                if isinstance(target, str):
                    tag = f"@{target}"
                else:
                    tag = f"<a href=\"tg://user?id={target}\">‌</a>"
            full_msg = f"{tag}\n{nhay_text}"
            try:
                await queue.put(full_msg)
            except asyncio.QueueFull:
                await asyncio.sleep(0.1)
        print(f"📦 Producer nhay {target_key} dừng")

    async def _producer_text(self, target_key, expected_count):
        """Theo dõi số lượng gửi, khi đủ thì tắt"""
        while spam_active.get(target_key, False):
            await asyncio.sleep(1)
            if total_sent.get(target_key, 0) >= expected_count:
                spam_active[target_key] = False
                stop_flags[target_key] = True
                break
        print(f"📦 Producer text {target_key} hoàn tất")

    async def stop_spam(self, target_key=None):
        """Dừng spam theo key, nếu None thì dừng tất cả"""
        if target_key is None:
            # Dừng tất cả
            for key in list(spam_active.keys()):
                spam_active[key] = False
                stop_flags[key] = True
            # Clear queues
            for q in message_queues.values():
                while not q.empty():
                    try:
                        q.get_nowait()
                    except:
                        pass
            print("🛑 Đã dừng tất cả spam")
        else:
            if target_key in spam_active:
                spam_active[target_key] = False
                stop_flags[target_key] = True
                # Clear queue
                if target_key in message_queues:
                    q = message_queues[target_key]
                    while not q.empty():
                        try:
                            q.get_nowait()
                        except:
                            pass
                print(f"🛑 Đã dừng {target_key}")

# Khởi tạo manager
manager = BotManager(TOKENS)
manager.start()

# ==================== HÀM KIỂM TRA OWNER ====================
def is_owner(message):
    return message.from_user.id == OWNER_ID

# ==================== HANDLER LỆNH ====================
@MAIN_BOT.message_handler(commands=['menu'])
def menu(message):
    if not is_owner(message):
        return
    text = """
🔥 <b> BOT MENU</b> 🔥

/sp1 <username> - Spam war 1 người (5 bot)
/sp2 - Spam nhây (nội dung từ nhay.txt) vào chính group hiện tại (tag group)
/sp3 <u1 u2 ...> - Spam war nhiều username
/sp4 <u1 u2 ...> - Spam nhây nhiều username
/sp5 <user_id> - Spam war bằng user_id (dùng link ẩn)
/sp6 <user_id> - Spam nhây bằng user_id
/sp7 <text> | <số lần> - Spam text thuần

/stop - Dừng tất cả spam
/stop <username> - Dừng spam user đó

/immom @u1 @u2 ... - Auto xoá tin nhắn của các user đó
/immom1 id1 id2 ... - Auto xoá tin nhắn bằng user_id
/rename on|off - Auto đổi tên group
/out - Tất cả bot rời group

"""
    MAIN_BOT.reply_to(message, text)

# ==================== SP1 ====================
@MAIN_BOT.message_handler(commands=['sp1'])
def sp1(message):
    if not is_owner(message):
        return
    try:
        parts = message.text.split()
        if len(parts) < 2:
            MAIN_BOT.reply_to(message, "❌ /sp1 username")
            return
        target = parts[1].lstrip('@')
        chat_id = message.chat.id
        # Tạo target_key
        key = f"war:{target}"
        if spam_active.get(key, False):
            MAIN_BOT.reply_to(message, f"⚠️ Đang spam {target} rồi. /stop {target} trước nếu muốn reset")
            return
        # Start spam war với 1 target
        asyncio.run_coroutine_threadsafe(
            manager.start_spam_war(key, chat_id, [target], use_tag_link=False),
            manager.loop
        )
        markup = types.InlineKeyboardMarkup()
        btn_stop = types.InlineKeyboardButton("🛑 DỪNG", callback_data=f"stop_{key}")
        btn_stats = types.InlineKeyboardButton("📊 STAT", callback_data=f"stats_{key}")
        markup.add(btn_stop, btn_stats)
        MAIN_BOT.reply_to(
            message,
            f"🚀 SPAM WAR 1 NGƯỜI: @{target}\n⚡ 5 bot, war {len(war_messages)} câu",
            reply_markup=markup
        )
    except Exception as e:
        MAIN_BOT.reply_to(message, f"❌ Lỗi: {str(e)}")

# ==================== SP2 ====================
@MAIN_BOT.message_handler(commands=['sp2'])
def sp2(message):
    if not is_owner(message):
        return
    try:
        chat_id = message.chat.id
        # Spam nhây vào group (target là group chat? Ta dùng key đặc biệt)
        # Có thể coi target là "group:chat_id"
        target_key = f"nhay:group_{chat_id}"
        if spam_active.get(target_key, False):
            MAIN_BOT.reply_to(message, "⚠️ Đang spam nhây trong group này rồi")
            return
        # Start spam nhây với target là None (chỉ gửi nội dung nhây, không tag ai)
        # Ta sẽ tạo một producer riêng không tag
        async def start():
            # Tạo queue và producer riêng không tag
            if target_key in message_queues:
                return
            spam_active[target_key] = True
            stop_flags[target_key] = False
            target_chat_id[target_key] = chat_id
            total_sent[target_key] = 0
            total_errors[target_key] = 0
            message_queues[target_key] = asyncio.Queue(maxsize=2000)
            # Producer nhay không tag
            async def producer_no_tag():
                nhay_text = "\n".join(nhay_messages)
                while spam_active.get(target_key, False):
                    await message_queues[target_key].put(nhay_text)
                    await asyncio.sleep(0.1)
            producer = manager.loop.create_task(producer_no_tag())
            producer_tasks[target_key] = producer
            for worker in manager.workers:
                task = manager.loop.create_task(worker.worker_loop(target_key, chat_id))
                worker.tasks.append(task)
        asyncio.run_coroutine_threadsafe(start(), manager.loop)
        markup = types.InlineKeyboardMarkup()
        btn_stop = types.InlineKeyboardButton("🛑 DỪNG", callback_data=f"stop_{target_key}")
        markup.add(btn_stop)
        MAIN_BOT.reply_to(
            message,
            f"🚀 SPAM NHÂY VÀO GROUP!\n📄 {len(nhay_messages)} dòng nhây",
            reply_markup=markup
        )
    except Exception as e:
        MAIN_BOT.reply_to(message, f"❌ Lỗi: {str(e)}")

# ==================== SP3 ====================
@MAIN_BOT.message_handler(commands=['sp3'])
def sp3(message):
    if not is_owner(message):
        return
    try:
        parts = message.text.split()
        if len(parts) < 2:
            MAIN_BOT.reply_to(message, "❌ /sp3 @u1 @u2 ...")
            return
        targets = [p.lstrip('@') for p in parts[1:]]
        chat_id = message.chat.id
        # Kiểm tra xem có target nào đang spam không
        existing = [t for t in targets if spam_active.get(f"war:{t}", False)]
        if existing:
            MAIN_BOT.reply_to(message, f"⚠️ Đang spam: {', '.join(existing)}. Hãy dừng trước.")
            return
        # Start spam cho từng target
        for t in targets:
            key = f"war:{t}"
            asyncio.run_coroutine_threadsafe(
                manager.start_spam_war(key, chat_id, [t], use_tag_link=False),
                manager.loop
            )
        markup = types.InlineKeyboardMarkup()
        # Nút dừng tất cả target này
        btn_stop_all = types.InlineKeyboardButton("🛑 DỪNG TẤT CẢ", callback_data=f"stop_multi_{chat_id}_{'_'.join(targets)}")
        markup.add(btn_stop_all)
        MAIN_BOT.reply_to(
            message,
            f"🚀 SPAM WAR {len(targets)} NGƯỜI: {', '.join(targets)}",
            reply_markup=markup
        )
    except Exception as e:
        MAIN_BOT.reply_to(message, f"❌ Lỗi: {str(e)}")

# ==================== SP4 ====================
@MAIN_BOT.message_handler(commands=['sp4'])
def sp4(message):
    if not is_owner(message):
        return
    try:
        parts = message.text.split()
        if len(parts) < 2:
            MAIN_BOT.reply_to(message, "❌ /sp4 @u1 @u2 ...")
            return
        targets = [p.lstrip('@') for p in parts[1:]]
        chat_id = message.chat.id
        existing = [t for t in targets if spam_active.get(f"nhay:{t}", False)]
        if existing:
            MAIN_BOT.reply_to(message, f"⚠️ Đang spam nhây: {', '.join(existing)}")
            return
        for t in targets:
            key = f"nhay:{t}"
            asyncio.run_coroutine_threadsafe(
                manager.start_spam_nhay(key, chat_id, [t], use_tag_link=False),
                manager.loop
            )
        markup = types.InlineKeyboardMarkup()
        btn_stop_all = types.InlineKeyboardButton("🛑 DỪNG TẤT CẢ", callback_data=f"stop_multi_{chat_id}_{'_'.join(targets)}")
        markup.add(btn_stop_all)
        MAIN_BOT.reply_to(
            message,
            f"🚀 SPAM NHÂY {len(targets)} NGƯỜI",
            reply_markup=markup
        )
    except Exception as e:
        MAIN_BOT.reply_to(message, f"❌ Lỗi: {str(e)}")

# ==================== SP5 ====================
@MAIN_BOT.message_handler(commands=['sp5'])
def sp5(message):
    if not is_owner(message):
        return
    try:
        parts = message.text.split()
        if len(parts) < 2:
            MAIN_BOT.reply_to(message, "❌ /sp5 user_id1 user_id2 ...")
            return
        user_ids = []
        for p in parts[1:]:
            try:
                user_ids.append(int(p))
            except:
                continue
        if not user_ids:
            MAIN_BOT.reply_to(message, "❌ user_id phải là số")
            return
        chat_id = message.chat.id
        for uid in user_ids:
            key = f"war:{uid}"
            if spam_active.get(key, False):
                continue
            asyncio.run_coroutine_threadsafe(
                manager.start_spam_war(key, chat_id, [uid], use_tag_link=True),
                manager.loop
            )
        MAIN_BOT.reply_to(message, f"🚀 SPAM WAR BẰNG ID: {user_ids}")
    except Exception as e:
        MAIN_BOT.reply_to(message, f"❌ Lỗi: {str(e)}")

# ==================== SP6 ====================
@MAIN_BOT.message_handler(commands=['sp6'])
def sp6(message):
    if not is_owner(message):
        return
    try:
        parts = message.text.split()
        if len(parts) < 2:
            MAIN_BOT.reply_to(message, "❌ /sp6 user_id1 user_id2 ...")
            return
        user_ids = []
        for p in parts[1:]:
            try:
                user_ids.append(int(p))
            except:
                continue
        if not user_ids:
            MAIN_BOT.reply_to(message, "❌ user_id phải là số")
            return
        chat_id = message.chat.id
        for uid in user_ids:
            key = f"nhay:{uid}"
            if spam_active.get(key, False):
                continue
            asyncio.run_coroutine_threadsafe(
                manager.start_spam_nhay(key, chat_id, [uid], use_tag_link=True),
                manager.loop
            )
        MAIN_BOT.reply_to(message, f"🚀 SPAM NHÂY BẰNG ID: {user_ids}")
    except Exception as e:
        MAIN_BOT.reply_to(message, f"❌ Lỗi: {str(e)}")

# ==================== SP7 ====================
@MAIN_BOT.message_handler(commands=['sp7'])
def sp7(message):
    if not is_owner(message):
        return
    try:
        text = message.text[4:].strip()
        if '|' not in text:
            MAIN_BOT.reply_to(message, "❌ /sp7 {text} | {số lần}")
            return
        parts = text.split('|')
        content = parts[0].strip()
        try:
            count = int(parts[1].strip())
        except:
            MAIN_BOT.reply_to(message, "❌ Số lần phải là số")
            return
        if count <= 0 or count > 10000:
            MAIN_BOT.reply_to(message, "❌ Số lần từ 1-10000")
            return
        chat_id = message.chat.id
        # Tạo key dựa trên hash nội dung để tránh trùng
        key = f"text:{hashlib.md5(content.encode()).hexdigest()[:8]}"
        if spam_active.get(key, False):
            MAIN_BOT.reply_to(message, "⚠️ Đang spam text này rồi")
            return
        asyncio.run_coroutine_threadsafe(
            manager.start_spam_text(key, chat_id, content, count),
            manager.loop
        )
        markup = types.InlineKeyboardMarkup()
        btn_stop = types.InlineKeyboardButton("🛑 DỪNG", callback_data=f"stop_{key}")
        markup.add(btn_stop)
        preview = escape(content[:50])
        MAIN_BOT.reply_to(
            message,
            f"🚀 SPAM TEXT {count} LẦN: <code>{preview}</code>...",
            parse_mode='HTML',
            reply_markup=markup
        )
    except Exception as e:
        MAIN_BOT.reply_to(message, f"❌ Lỗi: {str(e)}")

# ==================== STOP ====================
@MAIN_BOT.message_handler(commands=['stop'])
def stop(message):
    if not is_owner(message):
        return
    try:
        parts = message.text.split()
        if len(parts) == 1:
            # Dừng tất cả
            asyncio.run_coroutine_threadsafe(manager.stop_spam(), manager.loop)
            MAIN_BOT.reply_to(message, "🛑 Đã dừng TẤT CẢ spam")
        else:
            target_spec = parts[1].lstrip('@')
            # Tìm tất cả key liên quan đến target này (war, nhay)
            stopped = []
            for key in list(spam_active.keys()):
                if key.endswith(f":{target_spec}") or key.endswith(f":{target_spec}"):
                    asyncio.run_coroutine_threadsafe(manager.stop_spam(key), manager.loop)
                    stopped.append(key)
            if stopped:
                MAIN_BOT.reply_to(message, f"🛑 Đã dừng spam {target_spec}")
            else:
                MAIN_BOT.reply_to(message, f"❌ Không tìm thấy spam nào cho {target_spec}")
    except Exception as e:
        MAIN_BOT.reply_to(message, f"❌ Lỗi: {str(e)}")

# ==================== IMMOM ====================
@MAIN_BOT.message_handler(commands=['immom'])
def immom(message):
    if not is_owner(message):
        return
    try:
        parts = message.text.split()
        if len(parts) < 2:
            MAIN_BOT.reply_to(message, "❌ /immom @u1 @u2 ...")
            return
        usernames = [p.lstrip('@') for p in parts[1:]]
        for u in usernames:
            watch_usernames.add(u.lower())
        MAIN_BOT.reply_to(message, f"👁️ Đang theo dõi xoá tin nhắn của: {', '.join(usernames)}")
    except Exception as e:
        MAIN_BOT.reply_to(message, f"❌ Lỗi: {str(e)}")

@MAIN_BOT.message_handler(commands=['immom1'])
def immom1(message):
    if not is_owner(message):
        return
    try:
        parts = message.text.split()
        if len(parts) < 2:
            MAIN_BOT.reply_to(message, "❌ /immom1 id1 id2 ...")
            return
        for p in parts[1:]:
            try:
                uid = int(p)
                watch_users.add(uid)
            except:
                pass
        MAIN_BOT.reply_to(message, f"👁️ Đang theo dõi xoá tin nhắn của user_id: {parts[1:]}")
    except Exception as e:
        MAIN_BOT.reply_to(message, f"❌ Lỗi: {str(e)}")

# ==================== AUTO DELETE HANDLER ====================
@MAIN_BOT.message_handler(func=lambda msg: True, content_types=['text', 'photo', 'document', 'sticker', 'video', 'audio'])
def auto_delete(message):
    if not is_owner(message):  # Chỉ owner mới có thể dùng tính năng này? Thực ra ai cũng có thể bị xoá, nhưng lệnh chỉ owner mới set
        # Nhưng nếu đã set watch, thì phải xoá
        pass
    try:
        user_id = message.from_user.id
        username = message.from_user.username
        should_delete = False
        if user_id in watch_users:
            should_delete = True
        if username and username.lower() in watch_usernames:
            should_delete = True
        if should_delete:
            MAIN_BOT.delete_message(message.chat.id, message.message_id)
    except:
        pass

# ==================== RENAME ====================
@MAIN_BOT.message_handler(commands=['rename'])
def rename(message):
    if not is_owner(message):
        return
    global auto_rename_active, rename_thread
    try:
        parts = message.text.split()
        if len(parts) < 2:
            MAIN_BOT.reply_to(message, "❌ /rename on|off")
            return
        mode = parts[1].lower()
        if mode == 'on':
            if auto_rename_active:
                MAIN_BOT.reply_to(message, "⚠️ Auto rename đang bật rồi")
                return
            auto_rename_active = True
            # Chạy thread rename
            def rename_worker():
                while auto_rename_active:
                    try:
                        new_title = random.choice(group_titles) + f" [{random.randint(100,999)}]"
                        MAIN_BOT.set_chat_title(message.chat.id, new_title)
                        time.sleep(10)  # 10s đổi 1 lần
                    except:
                        time.sleep(5)
            rename_thread = threading.Thread(target=rename_worker, daemon=True)
            rename_thread.start()
            MAIN_BOT.reply_to(message, "✅ Auto rename ON")
        elif mode == 'off':
            auto_rename_active = False
            MAIN_BOT.reply_to(message, "✅ Auto rename OFF")
    except Exception as e:
        MAIN_BOT.reply_to(message, f"❌ Lỗi: {str(e)}")

# ==================== OUT ====================
@MAIN_BOT.message_handler(commands=['out'])
def out(message):
    if not is_owner(message):
        return
    try:
        chat_id = message.chat.id
        # Tất cả bot rời group
        for token in TOKENS:
            try:
                bot = TeleBot(token)
                bot.leave_chat(chat_id)
            except:
                pass
        MAIN_BOT.reply_to(message, "👋 Tạm biệt! Các bot đã rời group.")
    except Exception as e:
        MAIN_BOT.reply_to(message, f"❌ Lỗi: {str(e)}")

# ==================== CALLBACK ====================
@MAIN_BOT.callback_query_handler(func=lambda call: True)
def callback(call):
    if not is_owner(call.message):
        MAIN_BOT.answer_callback_query(call.id, "❌ Mày là ai?")
        return
    try:
        data = call.data
        if data.startswith('stop_'):
            key = data.replace('stop_', '')
            asyncio.run_coroutine_threadsafe(manager.stop_spam(key), manager.loop)
            MAIN_BOT.answer_callback_query(call.id, f"✅ Đã dừng {key}")
            MAIN_BOT.edit_message_text(
                f"🛑 ĐÃ DỪNG {key}",
                call.message.chat.id,
                call.message.message_id
            )
        elif data.startswith('stats_'):
            key = data.replace('stats_', '')
            sent = total_sent.get(key, 0)
            err = total_errors.get(key, 0)
            status = "🟢" if spam_active.get(key, False) else "🔴"
            MAIN_BOT.answer_callback_query(
                call.id,
                f"{status} {key}: Gửi {sent} | Lỗi {err}",
                show_alert=True
            )
        elif data.startswith('stop_multi_'):
            # Format: stop_multi_chatId_target1_target2...
            parts = data.split('_')
            chat_id = int(parts[2])
            targets = parts[3:]
            stopped = []
            for t in targets:
                for key in list(spam_active.keys()):
                    if key.endswith(f":{t}"):
                        asyncio.run_coroutine_threadsafe(manager.stop_spam(key), manager.loop)
                        stopped.append(t)
            MAIN_BOT.answer_callback_query(call.id, f"✅ Đã dừng {len(stopped)} target")
            MAIN_BOT.edit_message_text(
                f"🛑 ĐÃ DỪNG SPAM NHIỀU NGƯỜI",
                call.message.chat.id,
                call.message.message_id
            )
    except Exception as e:
        MAIN_BOT.answer_callback_query(call.id, f"Lỗi: {str(e)}")

# ==================== CHẠY BOT CHÍNH ====================
if __name__ == "__main__":
    print("🚀 SIÊU BOT CỦA CUONGDEVGPT ĐÃ KHỞI ĐỘNG!")
    print(f"👑 OWNER ID: {OWNER_ID}")
    print("📌 Đang chờ lệnh...")
    MAIN_BOT.infinity_polling()
#Wormgpt Cường Dev Don't Delete for copyright
