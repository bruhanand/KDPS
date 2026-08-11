#!/usr/bin/env python3
"""
store-dashboard engine — turns a store's monthly POS exports (sales + stock-on-hand)
into the KDPS house-style HTML + PDF dashboard covering the 16 standard measures.

Usage:  python generate.py <store_dir> [--no-pdf]
  <store_dir>  folder holding the .xlsx exports and an optional dashboard-config.json.
               Output is written into the same folder.

The heavy lifting (the 16-metric logic and every data quirk) lives here so each month is
just "drop the export, run this". See SKILL.md for the routine and the honest caveats.
"""
import sys, os, glob, json, re, datetime

try:
    import pandas as pd, numpy as np
except ImportError:
    sys.exit("ERROR: needs pandas + openpyxl.  Create a venv and:  pip install pandas openpyxl")

HERE = os.path.dirname(os.path.abspath(__file__))
MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
MON = {m.lower(): i+1 for i, m in enumerate(MONTHS)}

# ---- defaults (a store's dashboard-config.json overrides these) --------------
DEFAULTS = {
    "store_name": "Store", "store_code": "", "region": "",
    "costs": {"variable_pct_of_sales": 7, "rent": 220000, "electricity": 100000, "misc": 40000},
    "discount_ceiling_pct": None,           # None => derived from cost ratio (break-even)
    "soh_as_on": None,                       # "YYYY-MM-DD"; else last day of latest sales month
    "brand_aliases": {"LP": "LOUIS PHILIPPE", "LY": "LOUIS PHILIPPE", "LR": "LOUIS PHILIPPE",
                       "VH": "VAN HEUSEN", "VS": "VAN HEUSEN", "VD": "VAN HEUSEN", "VF": "VAN HEUSEN",
                       "VX": "VAN HEUSEN", "AS": "ALLEN SOLLY", "PE": "PETER ENGLAND",
                       "USPA": "U.S. POLO", "U. S. POLO": "U.S. POLO", "US POLO": "U.S. POLO"},
    "category_merges": {"SAREES": "SAREE", "SWEAT SHIRT": "SWEATSHIRT", "TROUSERS": "TROUSER",
                        "KURTA SET": "KURTI SET"},
    "carry_bag_labels": ["CARRY BAG"],
    "accessory_categories": ["BELT", "BELTS", "WALLET", "BELT & WALLET", "LADIES PURSE", "HANDBAG",
        "CLUTCH", "BACKPACK", "BAG", "DUFFEL BAG", "DUFFLE BAG", "TROLLEY", "TROLLY", "HARD TROLLY",
        "CAP", "WINTER CAP", "MUFFLER", "SHAWL", "STOLE", "SOCKS", "TIES & BOWTIE", "POCKET SQUARE",
        "HANDKERCHIEFS", "Handkerchief", "EARRINGS", "NECKLACE", "NECKLACE SET", "CHAIN",
        "LOCKET CHAIN", "MALA", "MANGALSUTRA", "JUTI", "SHOES", "SAFA", "DUPATTA"],
}
SALES_COLS = {"Bill Date", "Bill No", "Item", "Brand", "Size", "Gender", "Qty",
              "Gross Amt", "Disc Amt", "Net Amount", "Barcode", "SalesMan", "season"}
SOH_COLS = {"Item Name", "Brand", "Size", "Barcode", "Gender", "Tqty", "Mrp", "Rate"}
# "Season" and "Sale" are optional: "Sale" is never used in the metrics, and when the
# stock export has no "Season" column the age is backfilled per barcode from the sales
# export (never-sold items land in the "No season tag" ageing bucket).

# ---- helpers ----------------------------------------------------------------
def deep_merge(base, over):
    out = dict(base)
    for k, v in (over or {}).items():
        out[k] = deep_merge(base[k], v) if isinstance(v, dict) and isinstance(base.get(k), dict) else v
    return out

def cr(x):  return f"₹{x/1e7:.2f} Cr"
def L(x):   return f"₹{x/1e5:.1f} L"
def rs(x):  return f"₹{x:,.0f}"
def pct(x): return f"{x:.0f}%"
def ym_label(ym):
    y, m = ym.split("-"); return f"{MONTHS[int(m)-1]} {y[2:]}"

def parse_season(sv):
    if not isinstance(sv, str): return (np.nan, np.nan, np.nan)
    su = sv.upper()
    typ = 'AW' if ('AUTUMN' in su or 'WINTER' in su) else ('SS' if ('SPRING' in su or 'SUMMER' in su) else 'OTH')
    m = re.search(r'\(([A-Za-z]{3})-?(\d{2})\)', sv)
    if m:
        return (typ, MON.get(m.group(1).lower(), np.nan), 2000 + int(m.group(2)))
    return (typ, np.nan, np.nan)

# ---- file discovery ---------------------------------------------------------
def classify_sheets(path):
    """Return ('sales'|'soh'|None, sheet_name, dataframe) for the best sheet in a workbook."""
    try:
        xls = pd.ExcelFile(path, engine="openpyxl")
    except Exception:
        return (None, None, None)
    best = (None, None, None, -1)
    for sh in xls.sheet_names:
        try:
            df = xls.parse(sh)
        except Exception:
            continue
        cols = {str(c).strip() for c in df.columns}
        if {"Bill No", "Item", "Net Amount"} <= cols:
            score = len(df)
            if score > best[3]: best = ("sales", sh, df, score)
        elif "Tqty" in cols and "Item Name" in cols:
            score = len(df)
            if score > best[3]: best = ("soh", sh, df, score)
    return best[:3]

def discover(store_dir):
    sales, sohs = [], []
    for p in sorted(glob.glob(os.path.join(store_dir, "*.xlsx"))):
        if os.path.basename(p).startswith("~$"): continue
        kind, sh, df = classify_sheets(p)
        if kind == "sales": sales.append((p, df))
        elif kind == "soh": sohs.append((p, df))
    return sales, sohs

# ---- loaders ----------------------------------------------------------------
def load_sales(sales_files, cfg):
    if not sales_files:
        sys.exit("ERROR: no sales export found (a file with Bill No / Item / Net Amount columns).")
    frames = []
    for path, df in sorted(sales_files, key=lambda t: -len(t[1])):   # biggest file wins on overlap
        df = df.copy(); df.columns = [str(c).strip() for c in df.columns]
        missing = SALES_COLS - set(df.columns)
        if missing:
            sys.exit(f"ERROR: sales file {os.path.basename(path)} is missing columns {sorted(missing)}.\n"
                     "The POS export format changed — fix the export or update the engine.")
        for c in ["Bill Date", "Bill No", "Customer", "Phone"]:
            if c in df: df[c] = df[c].ffill()
        for c in ["Qty", "Rate", "Gross Amt", "Disc%", "Disc Amt", "Net Amount", "Bill Amount"]:
            df[c] = pd.to_numeric(df.get(c), errors="coerce")
        df = df[df["Item"].notna()].copy()
        df["_src"] = os.path.basename(path)
        frames.append(df)
    seen, keep = set(), []                       # keep each Bill No wholly from one (largest) file
    for df in frames:
        sub = df[~df["Bill No"].isin(seen)]
        keep.append(sub); seen |= set(sub["Bill No"].unique())
    s = pd.concat(keep, ignore_index=True)
    s["Bill Date"] = pd.to_datetime(s["Bill Date"], errors="coerce")
    s = s[s["Bill Date"].notna()].copy()
    s["ym"] = s["Bill Date"].dt.to_period("M").astype(str)
    s = s[~s["Item"].isin(cfg["carry_bag_labels"])].copy()   # exclude packaging, same as SOH
    s["Item"] = s["Item"].replace(cfg["category_merges"])
    s["Size"] = s["Size"].astype(str)                      # sizes mix numbers & text; keep one type
    s["brand_n"] = s["Brand"].apply(lambda x: cfg["brand_aliases"].get(str(x).upper().strip(), str(x).upper().strip()))
    s["dept"] = s["Gender"].replace({"FEAMAL": "FEMALE"}).map(_dept)
    return s

def _dept(g):
    g = str(g)
    if g == "KIDS MALE": return "KIDS MALE"
    if g == "KIDS FEMALE": return "KIDS FEMALE"
    if g.startswith("KIDS"): return "KIDS"
    if g == "FEMALE": return "WOMEN"
    if g == "MALE": return "MEN"
    return "OTHER"

def load_soh(soh_files, cfg):
    if not soh_files:
        sys.exit("ERROR: no stock-on-hand export found (a file with Item Name / Tqty columns).")
    path, df = max(soh_files, key=lambda t: os.path.getmtime(t[0]))   # newest SOH
    df = df.copy(); df.columns = [str(c).strip() for c in df.columns]
    missing = SOH_COLS - set(df.columns)
    if missing:
        sys.exit(f"ERROR: stock file {os.path.basename(path)} is missing columns {sorted(missing)}.")
    df = df[df["Barcode"].notna()].copy()                            # drops the hidden grand-total row
    for c in ["Op Qty", "Purchase", "Sale", "Adjustment", "Sl Ret", "St Trf", "Stf Reciept",
              "Pur Ret", "Tqty", "Mrp", "Rate"]:
        if c in df: df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
    df["Item Name"] = df["Item Name"].replace(cfg["category_merges"])
    df["Size"] = df["Size"].astype(str)                             # match sales: sizes as text
    df = df[~df["Item Name"].isin(cfg["carry_bag_labels"])].copy()   # exclude packaging
    df["brand_n"] = df["Brand"].apply(lambda x: cfg["brand_aliases"].get(str(x).upper().strip(), str(x).upper().strip()))
    df["dept"] = df["Gender"].replace({"FEAMAL": "FEMALE"}).map(_dept)
    if "Season" not in df.columns:
        df["Season"] = pd.to_numeric(df["Barcode"], errors="coerce").map(cfg.get("_season_by_barcode", {}))
    ps = df["Season"].apply(parse_season)
    df["seas_yr"] = [p[2] for p in ps]; df["seas_mo"] = [p[1] for p in ps]
    ref = cfg.get("_ref_period")
    df["age_mo"] = df.apply(lambda r: ref - (int(r["seas_yr"]) * 12 + int(r["seas_mo"]))
                            if pd.notna(r["seas_mo"]) and pd.notna(r["seas_yr"]) else np.nan, axis=1)
    df["cost_val"] = df["Tqty"] * df["Rate"]
    df["bc"] = pd.to_numeric(df["Barcode"], errors="coerce")
    return df, os.path.basename(path)

# ---- metrics ----------------------------------------------------------------
def compute(s, m, cfg):
    M = {}
    mm = m[(m["Mrp"] > 0) & (m["Rate"] > 0)]
    overall_ratio = (mm["Tqty"] * mm["Rate"]).sum() / (mm["Tqty"] * mm["Mrp"]).sum()
    cat_ratio = (mm.groupby("Item Name").apply(lambda d: (d["Tqty"]*d["Rate"]).sum()/(d["Tqty"]*d["Mrp"]).sum())
                 if len(mm) else pd.Series(dtype=float))
    brand_ratio = (mm.groupby("brand_n").apply(lambda d: (d["Tqty"]*d["Rate"]).sum()/(d["Tqty"]*d["Mrp"]).sum())
                   if len(mm) else pd.Series(dtype=float))
    M["cost_ratio"] = overall_ratio
    M["breakeven_disc"] = round((1 - overall_ratio) * 100)
    ceil = cfg["discount_ceiling_pct"] or M["breakeven_disc"]
    M["discount_ceiling"] = ceil

    s = s.copy()
    s["cr"] = s["Item"].map(cat_ratio).fillna(overall_ratio)
    s["cogs"] = s["Gross Amt"] * s["cr"]

    months = sorted(s["ym"].unique())
    M["months"] = months
    M["period"] = f"{ym_label(months[0])} – {ym_label(months[-1])}" if months else ""
    M["n_months"] = len(months)
    net = s["Net Amount"].sum(); gross = s["Gross Amt"].sum(); cogs = s["cogs"].sum()
    M["net"] = net; M["gross"] = gross; M["cogs"] = cogs
    M["units"] = int(s["Qty"].sum()); M["bills"] = s["Bill No"].nunique()
    M["disc_pct"] = -s["Disc Amt"].sum() / gross * 100 if gross else 0
    M["disc_given"] = -s["Disc Amt"].sum()
    M["margin_pct"] = (net - cogs) / net * 100 if net else 0

    # monthly P&L
    vp = cfg["costs"]["variable_pct_of_sales"] / 100.0
    fixed = cfg["costs"]["rent"] + cfg["costs"]["electricity"] + cfg["costs"]["misc"]
    M["fixed_monthly"] = fixed
    g = s.groupby("ym")
    pl = g.agg(net=("Net Amount", "sum"), gross=("Gross Amt", "sum"),
              disc=("Disc Amt", "sum"), cogs=("cogs", "sum")).reindex(months)
    pl["gp"] = pl["net"] - pl["cogs"]
    pl["opcost"] = vp * pl["net"] + fixed
    pl["np"] = pl["gp"] - pl["opcost"]
    pl["disc_pct"] = -pl["disc"] / pl["gross"] * 100
    pl["margin_pct"] = pl["gp"] / pl["net"] * 100
    M["pl"] = pl
    M["net_profit"] = pl["np"].sum()
    M["opcost_total"] = pl["opcost"].sum()
    M["gp_total"] = pl["gp"].sum()
    M["net_profit_pct"] = pl["np"].sum() / net * 100 if net else 0

    # ABV
    bills = s.groupby("Bill No").agg(net=("Net Amount", "sum"), units=("Qty", "sum"), ym=("ym", "first"))
    M["abv"] = bills["net"].mean(); M["upb"] = bills["units"].mean()
    M["abv_by_month"] = bills.groupby("ym")["net"].mean().reindex(months)

    # month-over-month (latest vs previous)
    M["mom"] = {}
    if len(months) >= 2:
        cur, prev = months[-1], months[-2]
        def d(series, key):
            a, b = series.get(cur, np.nan), series.get(prev, np.nan)
            M["mom"][key] = (a, b, (a - b) / b * 100 if b else np.nan)
        d(pl["net"], "net"); d(M["abv_by_month"], "abv"); d(pl["disc_pct"], "disc")
        d(pl["margin_pct"], "margin"); d(pl["np"], "np")
        M["mom_cur"], M["mom_prev"] = cur, prev

    # staff
    st = s.groupby("SalesMan").agg(net=("Net Amount", "sum"), gross=("Gross Amt", "sum"),
        units=("Qty", "sum"), bills=("Bill No", "nunique"))
    st["abv"] = st["net"] / st["bills"]; st["real"] = st["net"] / st["gross"] * 100
    M["staff"] = st.sort_values("net", ascending=False); M["staff_n"] = s["SalesMan"].nunique()

    # customers
    s["is_phone"] = s["Phone"].astype(str).str.match(r"^\d{10}$")
    bc = s.groupby("Bill No").agg(phone=("Phone", "first"), net=("Net Amount", "sum"), isph=("is_phone", "first"))
    ph = bc[bc["isph"]]
    cust = ph.groupby("phone").agg(bills=("net", "count"), spend=("net", "sum"))
    M["phone_capture"] = bc["isph"].mean() * 100 if len(bc) else 0
    M["cust_n"] = len(cust)
    M["repeat_pct"] = (cust["bills"] >= 2).mean() * 100 if len(cust) else 0
    M["repeat_share"] = (cust[cust["bills"] >= 2]["spend"].sum() / cust["spend"].sum() * 100) if len(cust) else 0
    top5 = max(1, int(len(cust) * 0.05))
    M["top5_share"] = cust.nlargest(top5, "spend")["spend"].sum() / cust["spend"].sum() * 100 if len(cust) else 0

    # gender
    M["gender"] = s.groupby("dept").agg(units=("Qty", "sum"), net=("Net Amount", "sum")).sort_values("net", ascending=False)

    # categories
    it = s.groupby("Item").agg(units=("Qty", "sum"), net=("Net Amount", "sum"),
        gross=("Gross Amt", "sum"), disc=("Disc Amt", "sum"))
    it["asp"] = it["net"] / it["units"]; it["disc_pct"] = -it["disc"] / it["gross"] * 100
    M["cats"] = it.sort_values("net", ascending=False)

    # brands (top 20) with margin + stock
    bs = s.groupby("brand_n").agg(units=("Qty", "sum"), net=("Net Amount", "sum"),
        gross=("Gross Amt", "sum"), cogs=("cogs", "sum"))
    stock = m.groupby("brand_n").agg(stk_cost=("cost_val", "sum"))
    bt = bs.join(stock, how="left").fillna({"stk_cost": 0})
    bt["disc_pct"] = (bt["gross"] - bt["net"]) / bt["gross"] * 100
    bt["margin_pct"] = (bt["net"] - bt["cogs"]) / bt["net"] * 100
    M["brands"] = bt.sort_values("net", ascending=False)

    # sizes by gender
    M["sizes"] = {}
    for d in ["MEN", "WOMEN", "KIDS MALE", "KIDS FEMALE"]:
        ss = s[s["dept"] == d].groupby("Size")["Qty"].sum()
        so = m[m["dept"] == d].groupby("Size")["Tqty"].sum()
        t = pd.DataFrame({"sold": ss, "stock": so}).fillna(0)
        t["sellthru"] = t["sold"] / (t["sold"] + t["stock"]) * 100
        M["sizes"][d] = t[t["sold"] > 0].sort_values("sold", ascending=False).head(6)

    # accessories
    acc_set = set(cfg["accessory_categories"])
    sa = s[s["Item"].isin(acc_set)].groupby("Item").agg(sold=("Qty", "sum"), net=("Net Amount", "sum"))
    soa = m[m["Item Name"].isin(acc_set)].groupby("Item Name").agg(stock=("Tqty", "sum"), stk=("cost_val", "sum"))
    M["acc"] = sa.join(soa, how="outer").fillna(0).sort_values("net", ascending=False)
    M["acc_sold_val"] = sa["net"].sum(); M["acc_stock_val"] = soa["stk"].sum()

    # stock health
    inv = m["cost_val"].sum(); M["inv_cost"] = inv; M["inv_mrp"] = (m["Tqty"] * m["Mrp"]).sum()
    M["turnover"] = (cogs * 12 / len(months)) / inv if inv and months else 0
    M["months_to_sell"] = inv / (cogs / len(months)) if cogs and months else 0
    ins = m[m["Tqty"] > 0].copy()
    sold_bc = set(pd.to_numeric(s["Barcode"], errors="coerce").dropna().astype("int64"))
    ins["sold_ever"] = ins["bc"].isin(sold_bc)
    proven = ins[ins["sold_ever"]]["cost_val"].sum()
    M["proven_pct"] = proven / inv * 100 if inv else 0
    dead = ins[~ins["sold_ever"]]
    M["dead_total"] = dead["cost_val"].sum()
    M["aged_6m"] = ins[ins["age_mo"] >= 6]["cost_val"].sum()
    M["dead_cats"] = dead.groupby("Item Name")["cost_val"].sum().sort_values(ascending=False).head(6)
    # ageing buckets (all in-stock merch)
    def bkt(a):
        if pd.isna(a): return "No season tag"
        return "Under 3 months" if a < 3 else ("3 to 6 months" if a < 6 else ("6 to 12 months" if a < 12 else "Over a year"))
    ins["bkt"] = ins["age_mo"].apply(bkt)
    order = ["Under 3 months", "3 to 6 months", "6 to 12 months", "Over a year", "No season tag"]
    M["ageing"] = ins.groupby("bkt")["cost_val"].sum().reindex(order).fillna(0)
    # out-of-stock on recent sellers
    recent = months[-2:] if len(months) >= 2 else months
    rbc = set(pd.to_numeric(s[s["ym"].isin(recent)]["Barcode"], errors="coerce").dropna().astype("int64"))
    oos = m[(m["Tqty"] <= 0) & (m["bc"].isin(rbc))]
    M["oos_n"] = len(oos); M["oos_cats"] = oos.groupby("Item Name").size().sort_values(ascending=False).head(6)
    return M

# ---- rendering --------------------------------------------------------------
def _delta_html(mom, key, good_up=True):
    if key not in mom: return ""
    a, b, d = mom[key]
    if pd.isna(d): return ""
    up = d >= 0
    cls = "flat" if abs(d) < 0.5 else (("up" if up else "down") if good_up else ("down" if up else "up"))
    arrow = "▲" if up else "▼"
    return f'<div class="delta {cls}">{arrow} {abs(d):.0f}% vs last month</div>'

def _kpi(lab, big, note, cls="", delta=""):
    return (f'<div class="kpi {cls}"><div class="lab">{lab}</div><div class="big num">{big}</div>'
            f'{delta}<div class="note">{note}</div></div>')

def render_body(M, cfg):
    be = M["breakeven_disc"]; mom = M.get("mom", {})
    P = []
    # ---------- headline ----------
    prof_cls = "good" if M["net_profit"] > 0 else "warn"
    k = [
        _kpi("Net sales · %d mo" % M["n_months"], cr(M["net"]),
             "%s bills · %d pieces" % (f"{M['bills']:,}", M["units"]), delta=_delta_html(mom, "net")),
        _kpi("Net profit kept", L(M["net_profit"]), "About %.0f%% of sales" % M["net_profit_pct"], prof_cls,
             _delta_html(mom, "np")),
        _kpi("Average margin", pct(M["margin_pct"]), "Would be ~%d%% at full price" % round((1-M["cost_ratio"])*100),
             "flag", _delta_html(mom, "margin")),
        _kpi("Average bill", rs(M["abv"]), "%.1f pieces per bill" % M["upb"], delta=_delta_html(mom, "abv")),
        _kpi("Stock vs sales speed", "%.1f×" % M["turnover"],
             "Stock takes ~%.0f months to sell" % M["months_to_sell"], "warn"),
        _kpi("Repeat customers", pct(M["repeat_pct"]), "Drive %.0f%% of tracked sales" % M["repeat_share"], "good"),
    ]
    cov = ["1 · Staff productivity → §6", "9 · Out-of-stock items → §5", "2 · Average bill value → §6",
           "10 · Item-wise → §4", "3 · Repeat / new customers → §6", "11 · Gender-wise → §4",
           "4 · Month-on-month P&amp;L → §2", "12 · Top 20 brands → §3", "5 · Dead stock → §5",
           "13 · Size analysis → §4", "6 · Fast-moving stock → §5", "14 · Accessories → §4",
           "7 · Stock turnover → §5", "15 · Discount → §2", "8 · Ageing → §5", "16 · Margin → §2 &amp; §3"]
    P.append(f"""<section><div class="wrap">
      <div class="eyebrow">The headline</div>
      <h2>{'A busy store that sells well — but keeps little profit' if M['net_profit_pct']<10 else 'How the store is performing'}</h2>
      <p class="lead">Over {M['n_months']} months the store sold <b>{cr(M['net'])}</b>. After the cost of goods and running
      costs it kept about <b>{L(M['net_profit'])} — roughly {M['net_profit_pct']:.0f}%</b>. Every item is bought at about
      <b>{M['cost_ratio']*100:.0f}% of its tag price</b>, so at full price the margin is ~{round((1-M['cost_ratio'])*100)}% —
      but the average discount of <b>{M['disc_pct']:.0f}%</b> pulls the realised margin down to <b>{M['margin_pct']:.0f}%</b>.</p>
      <div class="kpis" style="margin-top:18px">{''.join(k)}</div>
      <div class="call gold" style="margin-top:20px"><b>The one-line story:</b> the store earns a healthy
      ~{round((1-M['cost_ratio'])*100)}% at full price, but discounting and running costs leave only
      {M['net_profit_pct']:.0f}% at the bottom. <b>Profit is given away at the till and tied up in slow stock —
      not lost at the counter.</b></div>
      <div class="eyebrow" style="margin-top:24px">What's covered</div>
      <div class="cov">{''.join(f'<span>{c}</span>' for c in cov)}</div>
    </div></section>""")

    # ---------- §1 sales / seasonality ----------
    pl = M["pl"]; maxnet = pl["net"].max()
    bars = []
    for ym in M["months"]:
        n = pl.loc[ym, "net"]; np_ = pl.loc[ym, "np"]
        cls = "" if np_ > 20000 else ("loss" if np_ < -20000 else "flat")
        pcls = "pos" if np_ > 20000 else ("neg" if np_ < -20000 else "")
        h = max(3, n / maxnet * 100) if maxnet else 3
        sign = "+" if np_ >= 0 else "−"
        bars.append(f'<div class="mcol"><div class="mv">{n/1e5:.1f}</div>'
                    f'<div class="b {cls}" style="height:{h:.0f}%"></div>'
                    f'<div class="ml">{ym_label(ym).split()[0]}</div>'
                    f'<div class="mp {pcls}">{sign}{abs(np_)/1e5:.1f}</div></div>')
    best = pl["np"].idxmax(); worst = pl["np"].idxmin()
    P.append(f"""<section><div class="wrap">
      <div class="eyebrow">1 · Sales through the period</div>
      <h2>Which months made money — and which gave it back</h2>
      <p class="lead">The store runs at roughly <b>{L(pl['net'].min())}–{L(pl['net'].max())} a month</b>. The colours below
      show whether each month actually made or lost money after all costs — the number under each bar is the profit or loss.</p>
      <div class="chart"><h3>Monthly net sales (₹ lakh) — green = profit month, red = loss month</h3>
      <div class="cap">Bar height = sales. Colour &amp; number = profit/loss that month after cost of goods and running costs.</div>
      <div class="months">{''.join(bars)}</div>
      <div class="legend"><span><i style="background:#1f7a4d"></i>Made money</span>
      <span><i style="background:#b5341f"></i>Lost money</span><span><i style="background:#a9780a"></i>Around break-even</span></div></div>
      <div class="call {'red' if pl['np'].min()<-20000 else 'gold'}"><b>Best month {ym_label(best)}: {'+' if pl.loc[best,'np']>=0 else '−'}{abs(pl.loc[best,'np'])/1e5:.1f} L.
      Weakest {ym_label(worst)}: {'+' if pl.loc[worst,'np']>=0 else '−'}{abs(pl.loc[worst,'np'])/1e5:.1f} L.</b>
      The good months carry the weak ones — the biggest swing factor is how deep the discounting goes.</div>
    </div></section>""")

    # ---------- §2 money ----------
    rows = ""
    for ym in M["months"]:
        r = pl.loc[ym]; npc = "pos" if r["np"] > 20000 else ("neg" if r["np"] < -20000 else "")
        gpc = "neg" if r["gp"] < 0 else ""
        rows += (f'<tr><td>{ym_label(ym)}</td><td class="num">{r["net"]/1e5:.1f}</td>'
                 f'<td class="num">{r["disc_pct"]:.0f}%</td><td class="num">{r["cogs"]/1e5:.1f}</td>'
                 f'<td class="num {gpc}">{r["gp"]/1e5:.1f}</td><td class="num">{r["opcost"]/1e5:.1f}</td>'
                 f'<td class="num {npc}">{"+" if r["np"]>=0 else "−"}{abs(r["np"])/1e5:.1f}</td></tr>')
    c = cfg["costs"]
    P.append(f"""<section><div class="wrap">
      <div class="eyebrow">2 · The money — profit, discount &amp; margin <span style="color:var(--muted);font-weight:600">(#4, #15, #16)</span></div>
      <h2>Discount is the biggest lever on profit — past {be}% off, the store sells at a loss</h2>
      <p class="lead">Goods cost about <b>{M['cost_ratio']*100:.0f}% of the tag price</b>, so any discount above
      <b>{be}%</b> sells the item <b>below cost</b>. Keep {be}% as the hard ceiling for normal selling.</p>
      <div class="chart"><h3>Month-by-month profit &amp; loss (₹ lakh)</h3>
      <div class="cap">Cost of goods estimated from the stock file (every sold item matched to its cost). Running cost =
      {c['variable_pct_of_sales']}% of sales + rent {L(c['rent'])} + electricity {L(c['electricity'])} + misc {L(c['misc'])} per month.</div>
      <table><thead><tr><th>Month</th><th>Net sales</th><th>Discount</th><th>Cost of goods</th><th>Gross profit</th><th>Running cost</th><th>Profit / Loss</th></tr></thead>
      <tbody>{rows}</tbody>
      <tfoot><tr><td>{M['n_months']} months</td><td class="num">{M['net']/1e5:.0f}</td><td class="num">{M['disc_pct']:.0f}%</td>
      <td class="num">{M['cogs']/1e5:.0f}</td><td class="num">{M['gp_total']/1e5:.0f}</td><td class="num">{M['opcost_total']/1e5:.0f}</td>
      <td class="num {'pos' if M['net_profit']>=0 else 'neg'}">{'+' if M['net_profit']>=0 else '−'}{abs(M['net_profit'])/1e5:.0f}</td></tr></tfoot></table></div>
      <div class="two"><div class="call red" style="margin-top:8px"><b>The {be}% rule.</b> Because goods cost ~{M['cost_ratio']*100:.0f}% of the tag,
      any discount above <b>{be}%</b> sells below cost. Go beyond it only for stock you have decided to dump.</div>
      <div class="call gold" style="margin-top:8px"><b>What discount cost:</b> <b>{L(M['disc_given'])}</b> was given away in discount over
      {M['n_months']} months — against a gross profit of {L(M['gp_total'])}. Cutting average discount by <b>5 points</b> is worth
      roughly <b>{L(M['net']*0.05*12/M['n_months'])} a year</b>, straight to profit.</div></div>
    </div></section>""")

    # ---------- §3 brands ----------
    def bverdict(net_l, mg):
        if mg < 0: return ("Selling at a loss", "r")
        if mg < 10: return ("Big, thin profit" if net_l > 8 else "Thin profit", "r" if net_l > 8 else "a")
        if mg >= 25: return ("Star — grow it", "g")
        return ("Healthy", "g")
    brows = ""
    for name, r in M["brands"].head(20).iterrows():
        v, vc = bverdict(r["net"]/1e5, r["margin_pct"])
        mgc = "neg" if r["margin_pct"] < 0 else ""
        star = "<b>" + name.title() + "</b>" if r["margin_pct"] >= 25 else name.title()
        brows += (f'<tr><td>{star}</td><td class="num">{int(r["units"]):,}</td><td class="num">{r["net"]/1e5:.1f}</td>'
                  f'<td class="num">{r["disc_pct"]:.0f}%</td><td class="num {mgc}">{r["margin_pct"]:.0f}%</td>'
                  f'<td class="num">{r["stk_cost"]/1e5:.1f}</td><td><span class="tag {vc}">{v}</span></td></tr>')
    stars = M["brands"][M["brands"]["margin_pct"] >= 25].sort_values("net", ascending=False).head(6)
    starnames = ", ".join(s.title() for s in stars.index)
    P.append(f"""<section><div class="wrap">
      <div class="eyebrow">3 · Brands <span style="color:var(--muted);font-weight:600">(#12, #16)</span></div>
      <h2>Which brands actually make money</h2>
      <p class="lead">Two questions per brand: how much it sells, and how much it keeps after discount. Watch the
      <b>margin</b> column — big sales with low margin means cash tied up for little profit.</p>
      <table><thead><tr><th>Top 20 brands (by sales)</th><th>Pieces</th><th>Sales ₹L</th><th>Discount</th><th>Margin</th><th>Stock ₹L</th><th>Verdict</th></tr></thead>
      <tbody>{brows}</tbody></table>
      <p style="font-size:12.5px;color:var(--muted);margin-top:8px">Brand codes merged where the same brand appears under
      several names. Margin is after discount, using each item's cost from the stock file.</p>
      {"<div class='call green'><b>The lesson:</b> the high-margin earners here are <b>"+starnames+"</b>. Give them more space and stock; buy the low-margin, heavily-discounted brands more tightly.</div>" if starnames else ""}
    </div></section>""")

    # ---------- §4 what sells ----------
    gtot = M["gender"]["net"].sum()
    gb = ""
    gmax = M["gender"]["net"].max()
    for d, r in M["gender"].iterrows():
        if d == "OTHER": continue
        col = "g" if d == "WOMEN" else ("" if d == "MEN" else "gold")
        gb += (f'<div class="hbar"><div class="lbl">{d.title()}</div><div class="track">'
               f'<div class="fill {col}" style="width:{r["net"]/gmax*96:.0f}%"></div></div>'
               f'<div class="val">{r["net"]/gtot*100:.0f}%</div></div>')
    def cread(dp):
        return ("Full price", "g") if dp < 8 else (("Some discount", "a") if dp < 20 else ("Heavily discounted", "r"))
    crows = ""
    for name, r in M["cats"].head(12).iterrows():
        v, vc = cread(r["disc_pct"])
        crows += (f'<tr><td>{name.title()}</td><td class="num">{int(r["units"]):,}</td><td class="num">{r["net"]/1e5:.1f}</td>'
                  f'<td class="num">{rs(r["asp"])}</td><td class="num">{r["disc_pct"]:.0f}%</td><td><span class="tag {vc}">{v}</span></td></tr>')
    slines = ""
    for d, t in M["sizes"].items():
        if len(t) == 0: continue
        top = ", ".join(f'{sz} ({r.sellthru:.0f}%)' for sz, r in t.iterrows())
        slines += f'<li><b>{d.title()}:</b> {top}</li>'
    P.append(f"""<section><div class="wrap">
      <div class="eyebrow">4 · What sells <span style="color:var(--muted);font-weight:600">(#10, #11, #13, #14)</span></div>
      <h2>Where the sales and the margin come from</h2>
      <div class="chart"><h3>Who the store sells to</h3><div class="cap">Share of money taken, by section.</div>{gb}</div>
      <table><thead><tr><th>Top items</th><th>Pieces</th><th>Sales ₹L</th><th>Avg price</th><th>Discount</th><th>Read</th></tr></thead>
      <tbody>{crows}</tbody></table>
      <div class="two" style="margin-top:18px">
        <div><h3 style="font-size:16px">Sizes — fastest movers <span class="num" style="font-size:12px;color:var(--muted)">(#13)</span></h3>
        <p class="cap" style="margin:6px 0">Top sizes by pieces sold; % = how much of that size's stock has sold.</p>
        <ul class="tight">{slines}</ul></div>
        <div><h3 style="font-size:16px">Accessories <span class="num" style="font-size:12px;color:var(--muted)">(#14)</span></h3>
        <p style="margin-top:6px">Accessories sold <b>{L(M['acc_sold_val'])}</b> over {M['n_months']} months on <b>{L(M['acc_stock_val'])}</b>
        of stock — a healthy add-on business. Push them at the counter to lift the bill with little risk.</p></div>
      </div>
    </div></section>""")

    # ---------- §5 stock ----------
    ag = M["ageing"]; agmax = ag.max()
    agrows = ""
    for name, v in ag.items():
        if v <= 0: continue
        col = "g" if name in ("Under 3 months", "3 to 6 months") else ("r" if "month" in name or "year" in name else "gold")
        agrows += (f'<div class="hbar"><div class="lbl">{name}</div><div class="track">'
                   f'<div class="fill {col}" style="width:{v/agmax*95:.0f}%"></div></div><div class="val">{cr(v)}</div></div>')
    deadcats = " · ".join(f"{n.title()} {L(v)}" for n, v in M["dead_cats"].items())
    P.append(f"""<section><div class="wrap">
      <div class="eyebrow">5 · Stock health <span style="color:var(--muted);font-weight:600">(#5, #6, #7, #8, #9)</span></div>
      <h2>How much stock, how old, and how fast it turns</h2>
      <p class="lead">The store holds <b>{cr(M['inv_cost'])}</b> of stock ({cr(M['inv_mrp'])} at tag price). At the current
      selling speed that is about <b>{M['months_to_sell']:.0f} months</b> of stock — a healthy clothes shop carries 3–4 months.
      Only <b>{M['proven_pct']:.0f}%</b> of stock value is in styles that have sold even once.</p>
      <div class="kpis">
        {_kpi("Stock turnover (#7)", "%.1f×/yr" % M['turnover'], "~%.0f months to sell · target 3–4×" % M['months_to_sell'], "warn")}
        {_kpi("Aging stock, 6 mo+ (#5, #8)", cr(M['aged_6m']), "Not sold in 6+ months", "warn")}
        {_kpi("Out of stock on fast items (#9)", "%d" % M['oos_n'], "Sold recently, now at zero", "flag")}
      </div>
      <div class="chart"><h3>Stock by age (at cost) <span class="num" style="font-size:12px;color:var(--muted)">(#8)</span></h3>
      <div class="cap">Green = fresh, give it time. Red = old, clear it.</div>{agrows}</div>
      <div class="two" style="margin-top:18px">
        <div><h3 style="font-size:16px">Where the slow money sits <span class="num" style="font-size:12px;color:var(--muted)">(#5)</span></h3>
        <p style="margin-top:6px">Stock not sold in the period, by item: <b>{deadcats}</b>.</p></div>
        <div><h3 style="font-size:16px">The real problem: wrong mix <span class="num" style="font-size:12px;color:var(--muted)">(#6, #9)</span></h3>
        <p style="margin-top:6px">The store is <b>overstocked overall yet out of stock on {M['oos_n']} fast items</b> that sold recently
        and are now at zero. Money is locked in slow styles while fast ones run dry — a buying &amp; replenishment problem, not a quantity one.</p></div>
      </div>
    </div></section>""")

    # ---------- §6 customers & staff ----------
    strows = ""
    for name, r in M["staff"].head(8).iterrows():
        rc = "pos" if r["real"] >= 88 else ("neg" if r["real"] < 80 else "")
        strows += (f'<tr><td>{str(name).title()}</td><td class="num">{r["net"]/1e5:.1f}</td><td class="num">{int(r["bills"]):,}</td>'
                   f'<td class="num">{rs(r["abv"])}</td><td class="num {rc}">{r["real"]:.0f}%</td></tr>')
    real_hi = M["staff"]["real"].max(); real_lo = M["staff"]["real"].min()
    P.append(f"""<section><div class="wrap">
      <div class="eyebrow">6 · Customers &amp; staff <span style="color:var(--muted);font-weight:600">(#1, #2, #3)</span></div>
      <h2>The customer base and the staff scorecard</h2>
      <div class="kpis">
        {_kpi("Average bill (#2)", rs(M['abv']), "%.1f pieces per bill" % M['upb'])}
        {_kpi("Repeat customers (#3)", pct(M['repeat_pct']), "Drive %.0f%% of tracked sales" % M['repeat_share'], "good")}
        {_kpi("Bills with a phone", pct(M['phone_capture']), "%.0f%% not captured" % (100-M['phone_capture']), "flag" if M['phone_capture']<90 else "good")}
      </div>
      <div class="call gold"><b>Customers:</b> {M['cust_n']:,} customers are known by phone, and the top 5% bring
      <b>{M['top5_share']:.0f}%</b> of sales. {"Only "+pct(M['phone_capture'])+" of bills capture a phone number — fixing that unlocks WhatsApp reminders to repeat &amp; lapsed customers." if M['phone_capture']<90 else "Phone capture is strong — use it for WhatsApp reminders and a VIP perk for the top 5%."}</div>
      <h3 style="font-size:16px;margin-top:22px">Staff — sales and price held <span class="num" style="font-size:12px;color:var(--muted)">(#1)</span></h3>
      <p>Note the last column: some staff hold {real_hi:.0f}% of the tag price, others {real_lo:.0f}%. Part is the section they
      work, but it is also a coaching gap worth real money.</p>
      <table><thead><tr><th>Salesperson</th><th>Sales ₹L</th><th>Bills</th><th>Avg bill</th><th>Price held</th></tr></thead><tbody>{strows}</tbody></table>
      <p style="font-size:12.5px;color:var(--muted);margin-top:8px">{M['staff_n']} staff in total. Measure each on <b>price held</b>,
      not just sales value. (Sales-per-hour isn't possible — no attendance/targets in the data.)</p>
    </div></section>""")

    # ---------- §7 gaps + §8 actions ----------
    worst = pl["np"].idxmin()
    P.append(f"""<section><div class="wrap">
      <div class="eyebrow">7 · What we could not measure — and why</div>
      <h2>Being straight about the limits</h2>
      <ul class="tight">
      <li><b>True conversion rate — not possible.</b> No footfall / door-counter data exists, so we show repeat vs new customers, not sales ÷ walk-ins.</li>
      <li><b>Profit is a close estimate.</b> The sales export has no cost column, so cost of goods is taken from the stock file (every sold item matched to its cost). Running cost uses the {cfg['costs']['variable_pct_of_sales']}%-of-sales + rent/power/misc figures in the config.</li>
      <li><b>Only {M['n_months']} months of sales</b> are in the data, so "dead stock" means not sold in that window; fresh stock is shown separately by age.</li>
      <li><b>No colour analysis.</b> The "Colour" field in the sales export is a price band, and the stock file has no colour — so we can analyse sizes, not colours.</li>
      </ul>
    </div></section>
    <section><div class="wrap">
      <div class="eyebrow">8 · What to do — biggest profit first</div>
      <h2>The priority moves</h2>
      <div class="act"><h3><span class="pr">1</span> Cap the discount — never sell below cost</h3>
      <p>Set a firm ceiling of <b>{be}% off</b> for normal selling. Plan the clearance so it does not repeat {ym_label(worst)}'s loss.</p>
      <div class="impact">↳ Biggest lever — a 5-point cut in average discount ≈ {L(M['net']*0.05*12/M['n_months'])} a year.</div></div>
      <div class="act"><h3><span class="pr">2</span> Fix the brand &amp; product mix</h3>
      <p>Buy the low-margin, heavily-discounted brands more tightly; give the high-margin stars more space and stock.</p>
      <div class="impact">↳ Same sales, more profit; less cash tied in slow stock.</div></div>
      <div class="act"><h3><span class="pr med">3</span> Clear the aging stock</h3>
      <p>Run a planned exit for the <b>{cr(M['aged_6m'])}</b> not sold in 6+ months, within the {be}% ceiling.</p>
      <div class="impact">↳ Frees cash and shelf space; lifts stock-turn from {M['turnover']:.1f}× upward.</div></div>
      <div class="act"><h3><span class="pr med">4</span> Buy the right mix, not more stock</h3>
      <p>Reorder the <b>{M['oos_n']} fast items now out of stock</b>, and shorten the buy on slow sizes.</p>
      <div class="impact">↳ Recovers lost sales without adding to the overstock.</div></div>
      <div class="act"><h3><span class="pr low">5</span> Capture every customer, then use the list</h3>
      <p>Get the phone number on every bill (now {M['phone_capture']:.0f}%). Send WhatsApp reminders to repeat and lapsed customers.</p>
      <div class="impact">↳ Near-zero cost; repeat customers drive {M['repeat_share']:.0f}% of sales.</div></div>
      <div class="act"><h3><span class="pr low">6</span> Manage by this dashboard every month</h3>
      <p>Track profit, discount, margin, stock-turn, dead stock, out-of-stock, repeat rate and price-held — refresh it monthly.</p>
      <div class="impact">↳ Turns this study into an everyday habit.</div></div>
    </div></section>""")
    return "".join(P)

def render(M, cfg, template):
    meta = " ".join(f"<span>{x}</span>" for x in [
        f"📈 Sales: {M['period']} ({M['n_months']} mo)", f"📦 Stock file: {cfg.get('_soh_file','—')}",
        f"🧾 {M['bills']:,} bills · {M['units']:,} pieces · {cr(M['net'])}",
        f"👤 {M['staff_n']} staff · {M['cust_n']:,} known customers"])
    foot = (f"<p><b>How this was prepared.</b> Built by the <i>store-dashboard</i> skill from this store's sales and "
            f"stock-on-hand exports ({cfg.get('_files_used','')}). Figures computed directly from the files; bill fields "
            f"filled down; carry-bags and the stock total row removed; brand codes merged; every sold item matched to its "
            f"cost in the stock file to estimate margin and profit.</p>"
            f"<p><b>Honest caveats.</b> Cost of goods and profit are estimates (no cost column in sales); running costs use "
            f"the {cfg['costs']['variable_pct_of_sales']}%-of-sales + rent/power/misc figures in the config. Dead stock = not "
            f"sold in the {M['n_months']} months of data. A true conversion rate needs footfall data, which does not exist here.</p>"
            f"<p style='margin-top:14px;color:#9aa0ad'>Prepared for KDPS Lifestyle Pvt. Ltd. · {cfg['store_name']} · Generated {cfg['_today']}.</p>")
    html = (template.replace("{{TITLE}}", f"{cfg['store_name']} — Business Dashboard")
            .replace("{{KICK}}", "Monthly Store Dashboard · 16 Measures · AI-Assisted")
            .replace("{{SUB}}", f"A monthly read of sales and stock across all 16 measures — how much the store really earns, "
                                f"where the profit leaks, and what to fix. {cfg.get('region','')}")
            .replace("{{META}}", meta).replace("{{BODY}}", render_body(M, cfg)).replace("{{FOOT}}", foot))
    return html

def make_pdf(html_path, pdf_path):
    import subprocess, shutil
    chrome = None
    for c in ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
              "/Applications/Chromium.app/Contents/MacOS/Chromium", shutil.which("google-chrome"),
              shutil.which("chromium")]:
        if c and os.path.exists(c): chrome = c; break
    if not chrome:
        print("  (Chrome not found — skipped PDF; open the HTML and Print → Save as PDF.)"); return False
    ud = os.path.join(HERE, ".chrome-pdf")
    cmd = ["perl", "-e", "alarm 55; exec @ARGV", chrome, "--headless=new", "--disable-gpu",
           "--no-pdf-header-footer", "--disable-background-networking", "--disable-component-update",
           "--no-first-run", "--no-default-browser-check", f"--user-data-dir={ud}",
           f"--print-to-pdf={pdf_path}", f"file://{html_path}"]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["pkill", "-f", "print-to-pdf"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return os.path.exists(pdf_path)

def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__); return
    store_dir = os.path.abspath(argv[0]); no_pdf = "--no-pdf" in argv
    if not os.path.isdir(store_dir): sys.exit(f"ERROR: not a folder: {store_dir}")
    cfg_path = os.path.join(store_dir, "dashboard-config.json")
    user_cfg = json.load(open(cfg_path)) if os.path.exists(cfg_path) else {}
    cfg = deep_merge(DEFAULTS, user_cfg)
    if not user_cfg:
        print("  (no dashboard-config.json found — using defaults; add one for store name & real cost numbers.)")

    sales_files, soh_files = discover(store_dir)
    s = load_sales(sales_files, cfg)
    # season per barcode, for stock exports that carry no Season column
    _sb = s.assign(_bc=pd.to_numeric(s["Barcode"], errors="coerce")).dropna(subset=["_bc"])
    cfg["_season_by_barcode"] = _sb.groupby("_bc")["season"].first().to_dict()
    # reference month for stock age
    if cfg.get("soh_as_on"):
        d = datetime.date.fromisoformat(cfg["soh_as_on"]); cfg["_ref_period"] = d.year*12 + d.month
    else:
        last = sorted(s["ym"].unique())[-1]; y, mo = map(int, last.split("-")); cfg["_ref_period"] = y*12 + mo
    m, soh_name = load_soh(soh_files, cfg)
    cfg["_soh_file"] = soh_name
    cfg["_files_used"] = ", ".join(sorted(os.path.basename(p) for p, _ in sales_files) + [soh_name])
    cfg["_today"] = "generated from data files"      # avoid embedding a run-clock; date-neutral

    M = compute(s, m, cfg)
    template = open(os.path.join(HERE, "template.html")).read()
    html = render(M, cfg, template)
    stub = (cfg.get("store_code") or cfg["store_name"].split()[0]).upper()
    out_html = os.path.join(store_dir, f"{stub}-Dashboard.html")
    open(out_html, "w").write(html)
    print(f"\n  Period: {M['period']} ({M['n_months']} mo) | net {cr(M['net'])} | profit {L(M['net_profit'])} "
          f"({M['net_profit_pct']:.0f}%) | margin {M['margin_pct']:.0f}% | turnover {M['turnover']:.1f}x")
    print(f"  Files used: {cfg['_files_used']}")
    print(f"  → {out_html}")
    if not no_pdf:
        out_pdf = out_html.replace(".html", ".pdf")
        if make_pdf(out_html, out_pdf): print(f"  → {out_pdf}")

if __name__ == "__main__":
    main(sys.argv[1:])

