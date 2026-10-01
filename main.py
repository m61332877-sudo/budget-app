import http.server
import socketserver
import urllib.parse
import json
import sqlite3
import random
import os
from datetime import date

PORT = int(os.environ.get("PORT", 8080))
DB_FILE = "finance_secure.db"

otp_store = {}

def gregorian_to_jalali(gy, gm, gd):
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    gy2 = gy + 1 if gm > 2 else gy
    days = 355666 + (365 * gy) + ((gy2 + 3) // 4) - ((gy2 + 99) // 100) + ((gy2 + 399) // 400) + gd + g_d_m[gm - 1]
    jy = -1595 + (33 * (days // 12053))
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm = 1 + (days // 31)
        jd = 1 + (days % 31)
    else:
        jm = 7 + ((days - 186) // 30)
        jd = 1 + ((days - 186) % 30)
    return jy, jm, jd

def get_today_jalali():
    t = date.today()
    return gregorian_to_jalali(t.year, t.month, t.day)

def is_jalali_leap(jy):
    breaks = [-61, 9, 38, 199, 426, 686, 756, 818, 1111, 1181, 1210, 1635, 2060, 2097, 2192, 2262, 2324, 2394, 2456, 3178]
    jp = breaks[0]
    for j in breaks:
        jm = j
        if jy >= jm:
            jp = jm
        else:
            break
    n = jy - jp
    return (n % 33) in [1, 5, 9, 13, 17, 22, 26, 30]

def days_in_jalali_month(jy, jm):
    if 1 <= jm <= 6:
        return 31
    elif 7 <= jm <= 11:
        return 30
    elif jm == 12:
        return 30 if is_jalali_leap(jy) else 29
    return 30

SHAMSI_MONTHS = [
    "فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
    "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"
]

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        contact TEXT UNIQUE NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)
    c.execute("""
    CREATE TABLE IF NOT EXISTS categories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE,
        is_fixed INTEGER
    )
    """)
    c.execute("""
    CREATE TABLE IF NOT EXISTS expenses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        date TEXT,
        amount REAL,
        category_id INTEGER,
        description TEXT,
        FOREIGN KEY (user_id) REFERENCES users (id),
        FOREIGN KEY (category_id) REFERENCES categories (id)
    )
    """)
    c.execute("SELECT COUNT(*) FROM categories")
    if c.fetchone()[0] == 0:
        base_cats = [
            ("اجاره و مسکن", 1),
            ("قبوض و شارژ ساختمان", 1),
            ("اقساط وام و چک", 1),
            ("سوپرمارکت و خرید روزانه", 0),
            ("میوه، گوشت و پروتئین", 0),
            ("حمل‌‌ونقل، سوخت و اسنپ", 0),
            ("پزشکی و دارو", 0),
            ("رستوران و تفریح", 0),
            ("پوشاک و خرید متفرقه", 0)
        ]
        c.executemany("INSERT INTO categories (name, is_fixed) VALUES (?, ?)", base_cats)
        conn.commit()
    conn.close()

init_db()

HTML_PAGE = """<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>مدیریت دخل و خرج منزل | Mohammad Mahdi Heidari</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <link href="https://cdn.jsdelivr.net/gh/rastikerdar/vazirmatn@v33.003/Vazirmatn-font-face.css" rel="stylesheet">
    <style> body { font-family: 'Vazirmatn', sans-serif; } </style>
</head>
<body class="bg-slate-100 min-h-screen text-slate-800 flex flex-col justify-center">

    <div id="authSection" class="max-w-md w-full mx-auto p-6">
        <div class="bg-white p-8 rounded-3xl shadow-sm border border-slate-200 text-center space-y-6">
            <div class="w-16 h-16 bg-indigo-50 text-indigo-600 rounded-2xl flex items-center justify-center mx-auto text-3xl font-black">
                💰
            </div>
            <div>
                <h2 class="text-2xl font-black text-slate-800">ورود به حساب شخصی</h2>
                <p class="text-xs text-slate-500 mt-2">شماره تماس یا ایمیل خود را برای دریافت کد تایید وارد کنید.</p>
            </div>

            <div id="stepSendCode" class="space-y-4 text-right">
                <div>
                    <label class="block text-xs font-bold text-slate-600 mb-1">شماره تماس یا ایمیل</label>
                    <input type="text" id="contactInput" required placeholder="0912... یا email@example.com" dir="ltr" class="w-full border border-slate-300 rounded-xl p-3 text-sm focus:outline-indigo-500 text-center font-sans">
                </div>
                <button onclick="requestOTP()" class="w-full bg-indigo-600 hover:bg-indigo-700 text-white font-bold py-3 rounded-xl transition shadow-md">
                    ارسال کد تایید
                </button>
            </div>

            <div id="stepVerifyCode" class="hidden space-y-4 text-right">
                <div class="bg-amber-50 border border-amber-200 p-3 rounded-xl text-center">
                    <p class="text-xs text-amber-800">کد تایید ارسال شد.</p>
                    <p id="devOtpHint" class="text-xs font-bold text-indigo-700 mt-1"></p>
                </div>
                <div>
                    <label class="block text-xs font-bold text-slate-600 mb-1">کد ۴ رقمی ورود</label>
                    <input type="text" id="otpInput" maxlength="4" placeholder="1234" dir="ltr" class="w-full border border-slate-300 rounded-xl p-3 text-xl tracking-widest text-center font-bold focus:outline-indigo-500 font-sans">
                </div>
                <button onclick="verifyOTP()" class="w-full bg-emerald-600 hover:bg-emerald-700 text-white font-bold py-3 rounded-xl transition shadow-md">
                    تایید و ورود به برنامه
                </button>
                <button onclick="resetAuth()" class="w-full text-xs text-slate-400 hover:text-slate-600 text-center">
                    ویرایش شماره یا ایمیل
                </button>
            </div>

            <div class="pt-4 border-t border-slate-100">
                <p class="text-xs text-slate-400">توسعه‌داده شده توسط:</p>
                <p class="text-xs font-bold text-slate-600 mt-0.5">Mohammad Mahdi Heidari</p>
            </div>
        </div>
    </div>

    <div id="dashboardSection" class="hidden max-w-5xl w-full mx-auto p-4 md:p-8 space-y-6">
        <header class="bg-white p-5 rounded-2xl shadow-sm flex flex-col md:flex-row justify-between items-center gap-4 border border-slate-200">
            <div>
                <h1 class="text-2xl font-black text-indigo-700">سامانه مدیریت دخل و خرج منزل</h1>
                <p class="text-xs text-slate-500 mt-1">حساب: <span id="userBadge" class="font-bold text-slate-700 font-sans"></span></p>
            </div>
            <div class="flex items-center gap-2">
                <div class="flex items-center gap-2 bg-slate-50 p-1.5 rounded-xl border border-slate-200">
                    <select id="filterYear" class="border border-slate-300 rounded-lg px-2 py-1 text-sm bg-white font-sans focus:outline-indigo-500" onchange="loadReport()"></select>
                    <select id="filterMonth" class="border border-slate-300 rounded-lg px-2 py-1 text-sm bg-white font-sans focus:outline-indigo-500" onchange="loadReport()"></select>
                </div>
                <button onclick="logout()" class="text-xs bg-rose-50 text-rose-600 hover:bg-rose-100 font-bold px-3 py-2 rounded-xl transition">
                    خروج
                </button>
            </div>
        </header>

        <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <div class="bg-white p-5 rounded-2xl shadow-sm border border-slate-200">
                <span class="text-xs font-semibold text-slate-500">مخارج این ماه شما</span>
                <div id="cardCurrent" class="text-2xl font-black text-slate-800 mt-2">۰ تومان</div>
                <div id="cardMomBadge" class="mt-2 text-xs font-bold inline-block px-2.5 py-1 rounded-full bg-slate-100 text-slate-600">محاسبه...</div>
            </div>

            <div class="bg-white p-5 rounded-2xl shadow-sm border border-slate-200">
                <span class="text-xs font-semibold text-slate-500">مخارج ماه گذشته</span>
                <div id="cardPrev" class="text-2xl font-black text-slate-600 mt-2">۰ تومان</div>
                <span id="prevMonthName" class="text-xs text-slate-400 mt-2 block">مبنای مقایسه</span>
            </div>

            <div class="bg-white p-5 rounded-2xl shadow-sm border border-slate-200">
                <span class="text-xs font-semibold text-slate-500">خرج روزانه متغیر</span>
                <div id="cardDaily" class="text-2xl font-black text-amber-600 mt-2">۰ تومان</div>
                <span id="cardDays" class="text-xs text-slate-400 mt-2 block">۰ روز تا آخر ماه</span>
            </div>

            <div class="bg-gradient-to-br from-indigo-700 to-slate-900 text-white p-5 rounded-2xl shadow-md">
                <span class="text-xs font-semibold text-indigo-200">پیش‌بینی کل مخارج پایان ماه</span>
                <div id="cardForecast" class="text-2xl font-black text-amber-300 mt-2">۰ تومان</div>
                <span class="text-xs text-indigo-100/70 mt-2 block">بر مبنای سرعت خرج متغیر شما</span>
            </div>
        </div>

        <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <div class="bg-white p-6 rounded-2xl shadow-sm border border-slate-200">
                <h2 class="text-lg font-bold mb-4 text-slate-800">➕ ثبت هزینه جدید</h2>
                <form id="expForm" onsubmit="saveExpense(event)" class="space-y-4">
                    <div>
                        <label class="block text-xs font-bold text-slate-600 mb-1">تاریخ شمسی</label>
                        <div class="grid grid-cols-3 gap-1">
                            <input type="number" id="inDay" min="1" max="31" placeholder="روز" required class="border border-slate-300 rounded-lg p-2 text-center text-sm font-sans focus:outline-indigo-500">
                            <select id="inMonth" class="border border-slate-300 rounded-lg p-2 text-xs font-sans focus:outline-indigo-500"></select>
                            <input type="number" id="inYear" min="1400" max="1450" placeholder="سال" required class="border border-slate-300 rounded-lg p-2 text-center text-sm font-sans focus:outline-indigo-500">
                        </div>
                    </div>

                    <div>
                        <label class="block text-xs font-bold text-slate-600 mb-1">مبلغ (تومان)</label>
                        <input type="number" id="formAmount" placeholder="مثلاً: ۲۵۰۰۰۰" required min="1" class="w-full border border-slate-300 rounded-xl p-2.5 text-sm focus:outline-indigo-500">
                    </div>

                    <div>
                        <label class="block text-xs font-bold text-slate-600 mb-1">دسته‌بندی</label>
                        <select id="formCategory" class="w-full border border-slate-300 rounded-xl p-2.5 text-sm focus:outline-indigo-500"></select>
                    </div>

                    <div>
                        <label class="block text-xs font-bold text-slate-600 mb-1">توضیحات (اختیاری)</label>
                        <input type="text" id="formDesc" placeholder="مثلاً: خرید پروتئین و سوپرمارکت" class="w-full border border-slate-300 rounded-xl p-2.5 text-sm focus:outline-indigo-500">
                    </div>

                    <button type="submit" class="w-full bg-indigo-600 hover:bg-indigo-700 text-white font-bold py-3 rounded-xl transition shadow-sm">
                        ثبت در دفتر حساب
                    </button>
                </form>
            </div>

            <div class="lg:col-span-2 bg-white p-6 rounded-2xl shadow-sm border border-slate-200 flex flex-col justify-between">
                <div>
                    <h2 class="text-lg font-bold text-slate-800">📊 مقایسه مخارج به تفکیک دسته‌ها</h2>
                    <p class="text-xs text-slate-400 mt-1">تغییرات ماه انتخابی در برابر ماه گذشته</p>
                </div>
                <div class="h-72 mt-4">
                    <canvas id="chartCanvas"></canvas>
                </div>
            </div>
        </div>

        <footer class="text-center py-4">
            <p class="text-xs text-slate-400">
                توسعه‌داده شده توسط: <span class="font-bold text-slate-600">Mohammad Mahdi Heidari</span>
            </p>
        </footer>
    </div>

    <script>
        const monthNames = ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور", "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"];
        let myChart = null;
        let currentUser = null;
        let pendingContact = "";

        window.onload = function() {
            const saved = localStorage.getItem('budget_user');
            if (saved) {
                currentUser = JSON.parse(saved);
                showDashboard();
            }
        };

        async function requestOTP() {
            const contact = document.getElementById('contactInput').value.trim();
            if (!contact) {
                alert("لطفاً شماره تماس یا ایمیل خود را وارد کنید.");
                return;
            }
            pendingContact = contact;

            const res = await fetch('/api/send_otp', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ contact })
            });

            const data = await res.json();
            if (res.ok) {
                document.getElementById('stepSendCode').classList.add('hidden');
                document.getElementById('stepVerifyCode').classList.remove('hidden');
                document.getElementById('devOtpHint').textContent = `کد تایید شما: ${data.code}`;
                document.getElementById('otpInput').focus();
            }
        }

        async function verifyOTP() {
            const code = document.getElementById('otpInput').value.trim();
            if (!code) {
                alert("لطفاً کد تایید را وارد کنید.");
                return;
            }

            const res = await fetch('/api/verify_otp', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ contact: pendingContact, code })
            });

            if (res.ok) {
                currentUser = await res.json();
                localStorage.setItem('budget_user', JSON.stringify(currentUser));
                showDashboard();
            } else {
                alert("کد وارد شده اشتباه یا منقضی شده است.");
            }
        }

        function resetAuth() {
            document.getElementById('stepVerifyCode').classList.add('hidden');
            document.getElementById('stepSendCode').classList.remove('hidden');
            document.getElementById('otpInput').value = '';
        }

        function logout() {
            localStorage.removeItem('budget_user');
            currentUser = null;
            resetAuth();
            document.getElementById('dashboardSection').classList.add('hidden');
            document.getElementById('authSection').classList.remove('hidden');
            document.body.className = "bg-slate-100 min-h-screen text-slate-800 flex flex-col justify-center";
        }

        async function showDashboard() {
            document.getElementById('authSection').classList.add('hidden');
            document.getElementById('dashboardSection').classList.remove('hidden');
            document.body.className = "bg-slate-100 min-h-screen text-slate-800 p-4 md:p-8";
            document.getElementById('userBadge').textContent = currentUser.contact;

            const res = await fetch('/api/today');
            const today = await res.json();

            const inM = document.getElementById('inMonth');
            const filM = document.getElementById('filterMonth');
            inM.innerHTML = '';
            filM.innerHTML = '';
            monthNames.forEach((m, idx) => {
                const val = idx + 1;
                inM.add(new Option(m, val));
                filM.add(new Option(m, val));
            });

            const filY = document.getElementById('filterYear');
            filY.innerHTML = '';
            for (let y = today.year - 2; y <= today.year + 2; y++) {
                filY.add(new Option(y, y));
            }

            document.getElementById('inYear').value = today.year;
            document.getElementById('inMonth').value = today.month;
            document.getElementById('inDay').value = today.day;
            filY.value = today.year;
            filM.value = today.month;

            loadCategories();
            loadReport();
        }

        function formatMoney(num) {
            return Number(Math.round(num)).toLocaleString('fa-IR') + ' تومان';
        }

        async function loadCategories() {
            const res = await fetch('/api/categories');
            const cats = await res.json();
            const sel = document.getElementById('formCategory');
            sel.innerHTML = '';
            cats.forEach(c => {
                const opt = document.createElement('option');
                opt.value = c.id;
                opt.textContent = `${c.name} (${c.is_fixed ? 'ثابت' : 'متغیر'})`;
                sel.appendChild(opt);
            });
        }

        async function saveExpense(e) {
            e.preventDefault();
            const y = document.getElementById('inYear').value;
            const m = String(document.getElementById('inMonth').value).padStart(2, '0');
            const d = String(document.getElementById('inDay').value).padStart(2, '0');

            const payload = {
                user_id: currentUser.id,
                date: `${y}/${m}/${d}`,
                amount: parseFloat(document.getElementById('formAmount').value),
                category_id: parseInt(document.getElementById('formCategory').value),
                description: document.getElementById('formDesc').value
            };

            await fetch('/api/add_expense', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(payload)
            });

            document.getElementById('formAmount').value = '';
            document.getElementById('formDesc').value = '';
            loadReport();
        }

        async function loadReport() {
            if (!currentUser) return;
            const y = document.getElementById('filterYear').value;
            const m = document.getElementById('filterMonth').value;

            const res = await fetch(`/api/report?user_id=${currentUser.id}&year=${y}&month=${m}`);
            const data = await res.json();

            document.getElementById('cardCurrent').textContent = formatMoney(data.cur_total);
            document.getElementById('cardPrev').textContent = formatMoney(data.prev_total);
            document.getElementById('cardDaily').textContent = formatMoney(data.daily_burn);
            document.getElementById('cardDays').textContent = `${data.days_left} روز باقیمانده تا پایان ماه`;
            document.getElementById('cardForecast').textContent = formatMoney(data.forecast_total);
            document.getElementById('prevMonthName').textContent = `مبنا: ${data.prev_month_label}`;

            const badge = document.getElementById('cardMomBadge');
            const pct = data.mom_pct;
            if (pct > 0) {
                badge.className = 'mt-2 text-xs font-bold inline-block px-2.5 py-1 rounded-full bg-rose-100 text-rose-700';
                badge.textContent = `🔺 ${Math.abs(pct).toFixed(1)}٪ افزایش نسبت به ماه قبل`;
            } else if (pct < 0) {
                badge.className = 'mt-2 text-xs font-bold inline-block px-2.5 py-1 rounded-full bg-emerald-100 text-emerald-700';
                badge.textContent = `🔻 ${Math.abs(pct).toFixed(1)}٪ صرفه‌جویی نسبت به ماه قبل`;
            } else {
                badge.className = 'mt-2 text-xs font-bold inline-block px-2.5 py-1 rounded-full bg-slate-100 text-slate-600';
                badge.textContent = 'برابر با ماه گذشته';
            }

            renderChart(data.cat_data, data.cur_month_label, data.prev_month_label);
        }

        function renderChart(items, curLabel, prevLabel) {
            const ctx = document.getElementById('chartCanvas').getContext('2d');
            const labels = items.map(x => x.name);
            const prevs = items.map(x => x.prev);
            const curs = items.map(x => x.cur);

            if (myChart) myChart.destroy();

            myChart = new Chart(ctx, {
                type: 'bar',
                data: {
                    labels: labels,
                    datasets: [
                        { label: prevLabel, data: prevs, backgroundColor: '#94a3b8', borderRadius: 6 },
                        { label: curLabel, data: curs, backgroundColor: '#4f46e5', borderRadius: 6 }
                    ]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { position: 'top', rtl: true, labels: { font: { family: 'Vazirmatn' } } }
                    }
                }
            });
        }
    </script>
</body>
</html>
"""

class WebHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        if url.path in ["", "/"]:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_PAGE.encode("utf-8"))

        elif url.path == "/api/today":
            jy, jm, jd = get_today_jalali()
            self.send_json({"year": jy, "month": jm, "day": jd})

        elif url.path == "/api/categories":
            conn = sqlite3.connect(DB_FILE)
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT id, name, is_fixed FROM categories").fetchall()
            conn.close()
            self.send_json([dict(r) for r in rows])

        elif url.path == "/api/report":
            params = urllib.parse.parse_qs(url.query)
            user_id = int(params.get("user_id", [0])[0])
            today_y, today_m, today_d = get_today_jalali()
            year = int(params.get("year", [today_y])[0])
            month = int(params.get("month", [today_m])[0])

            total_days = days_in_jalali_month(year, month)
            start_cur = f"{year:04d}/{month:02d}/01"
            end_cur = f"{year:04d}/{month:02d}/{total_days:02d}"

            if month == 1:
                prev_y = year - 1
                prev_m = 12
            else:
                prev_y = year
                prev_m = month - 1
            prev_total_days = days_in_jalali_month(prev_y, prev_m)
            start_prev = f"{prev_y:04d}/{prev_m:02d}/01"
            end_prev = f"{prev_y:04d}/{prev_m:02d}/{prev_total_days:02d}"

            conn = sqlite3.connect(DB_FILE)
            conn.row_factory = sqlite3.Row

            rows = conn.execute("""
                SELECT c.is_fixed, SUM(e.amount) as total
                FROM expenses e JOIN categories c ON e.category_id = c.id
                WHERE e.user_id = ? AND e.date BETWEEN ? AND ?
                GROUP BY c.is_fixed
            """, (user_id, start_cur, end_cur)).fetchall()

            fixed_spent = 0.0
            var_spent = 0.0
            for r in rows:
                if r["is_fixed"] == 1:
                    fixed_spent = r["total"] or 0.0
                else:
                    var_spent = r["total"] or 0.0
            cur_total = fixed_spent + var_spent

            row_p = conn.execute("""
                SELECT SUM(amount) as total FROM expenses
                WHERE user_id = ? AND date BETWEEN ? AND ?
            """, (user_id, start_prev, end_prev)).fetchone()
            prev_total = row_p["total"] or 0.0 if row_p and row_p["total"] else 0.0

            cat_rows = conn.execute("""
                SELECT c.name,
                    SUM(CASE WHEN e.date BETWEEN ? AND ? THEN e.amount ELSE 0 END) as cur_val,
                    SUM(CASE WHEN e.date BETWEEN ? AND ? THEN e.amount ELSE 0 END) as prev_val
                FROM categories c
                LEFT JOIN expenses e ON c.id = e.category_id AND e.user_id = ?
                GROUP BY c.id
                HAVING cur_val > 0 OR prev_val > 0
            """, (start_cur, end_cur, start_prev, end_prev, user_id)).fetchall()
            conn.close()

            if today_y == year and today_m == month:
                passed_days = today_d
            elif (year < today_y) or (year == today_y and month < today_m):
                passed_days = total_days
            else:
                passed_days = 0

            days_left = max(0, total_days - passed_days)
            if passed_days > 0 and days_left > 0:
                daily_burn = var_spent / passed_days
                forecast_total = fixed_spent + var_spent + (daily_burn * days_left)
            else:
                daily_burn = 0.0
                forecast_total = cur_total

            mom_pct = ((cur_total - prev_total) / prev_total * 100) if prev_total > 0 else 0.0
            cat_data = [{"name": r["name"], "cur": r["cur_val"] or 0, "prev": r["prev_val"] or 0} for r in cat_rows]

            self.send_json({
                "cur_total": cur_total,
                "prev_total": prev_total,
                "mom_pct": mom_pct,
                "daily_burn": daily_burn,
                "days_left": days_left,
                "forecast_total": forecast_total,
                "cat_data": cat_data,
                "cur_month_label": f"{SHAMSI_MONTHS[month - 1]} {year}",
                "prev_month_label": f"{SHAMSI_MONTHS[prev_m - 1]} {prev_y}"
            })

    def do_POST(self):
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length)
        body = json.loads(post_data.decode('utf-8'))

        if self.path == "/api/send_otp":
            contact = body.get("contact", "").strip()
            code = str(random.randint(1000, 9999))
            otp_store[contact] = code
            self.send_json({"status": "sent", "code": code})

        elif self.path == "/api/verify_otp":
            contact = body.get("contact", "").strip()
            code = body.get("code", "").strip()

            if otp_store.get(contact) == code:
                del otp_store[contact]
                conn = sqlite3.connect(DB_FILE)
                conn.row_factory = sqlite3.Row
                c = conn.cursor()
                c.execute("SELECT id, contact FROM users WHERE contact = ?", (contact,))
                user = c.fetchone()
                if not user:
                    c.execute("INSERT INTO users (contact) VALUES (?)", (contact,))
                    conn.commit()
                    user_id = c.lastrowid
                else:
                    user_id = user["id"]
                conn.close()

                self.send_json({"id": user_id, "contact": contact})
            else:
                self.send_response(401)
                self.end_headers()
                self.wfile.write(b'{"error": "invalid_code"}')

        elif self.path == "/api/add_expense":
            conn = sqlite3.connect(DB_FILE)
            conn.execute(
                "INSERT INTO expenses (user_id, date, amount, category_id, description) VALUES (?, ?, ?, ?, ?)",
                (body["user_id"], body["date"], body["amount"], body["category_id"], body["description"])
            )
            conn.commit()
            conn.close()
            self.send_json({"status": "ok"})

    def send_json(self, data):
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))

if __name__ == "__main__":
    with socketserver.TCPServer(("", PORT), WebHandler) as httpd:
        print(f"Server started on port {PORT}")
        httpd.serve_forever()
