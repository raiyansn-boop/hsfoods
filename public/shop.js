const $ = (s) => document.querySelector(s);
const api = async (path, opts) => {
  const res = await fetch('/api' + path, { headers: { 'Content-Type': 'application/json' }, ...opts });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.statusText);
  return res.json();
};
const rupee = (n) => '₹' + Number(n || 0).toLocaleString('en-IN', { maximumFractionDigits: 2 });
const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

// --- state (in-memory-first storage; survives Custom Tabs that block localStorage) ---
const _mem = {};
const LS = {
  get(k) { if (k in _mem) return _mem[k]; try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { _mem[k] = v; try { localStorage.setItem(k, v); } catch {} },
  remove(k) { delete _mem[k]; try { localStorage.removeItem(k); } catch {} },
};
const store = {
  get phone() { return LS.get('hs_phone') || ''; },
  get name() { return LS.get('hs_name') || ''; },
  get cart() { try { return JSON.parse(LS.get('hs_cart') || '{}'); } catch { return {}; } },
  set cart(c) { LS.set('hs_cart', JSON.stringify(c)); },
};
let PRODUCTS = [];
let CATS = [];
let CTX = { wallet: 0, walletPending: 0, address: '', name: '', referralCode: '' };
let activeCat = null;
let lastQuery = '';
let detailId = null;

function toast(msg) {
  const t = $('#toast'); t.textContent = msg; t.classList.add('show');
  clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.remove('show'), 1800);
}

// --- onboarding (OTP login) --------------------------------------------------
let pendingPhone = '';
function showLoginStep(n) {
  $('#loginStep1').hidden = n !== 1;
  $('#loginStep2').hidden = n !== 2;
}
async function sendOtp() {
  const phone = ($('#obPhone').value || '').replace(/\D/g, '');
  if (phone.length < 8) { toast('Enter a valid number'); return; }
  const nameEl = $('#obName'); if (nameEl && nameEl.value.trim()) LS.set('hs_name', nameEl.value.trim());
  const refEl = $('#obRef'); if (refEl && refEl.value.trim()) LS.set('hs_ref', refEl.value.trim());
  const btn = $('#obSendOtp'); const label = btn.textContent;
  btn.disabled = true; btn.textContent = 'Sending…';
  try {
    const r = await api('/shop/auth/send-otp', { method: 'POST', body: JSON.stringify({ phone }) });
    pendingPhone = phone;
    $('#otpPhoneLabel').textContent = '+' + phone;
    $('#obOtp').value = '';
    const dev = $('#otpDev');
    if (r.devMode && r.devCode) {
      dev.hidden = false;
      dev.innerHTML = "Demo mode — WhatsApp messaging isn't set up yet.<br>Your code is <b>" + esc(r.devCode) + '</b>';
      $('#obOtp').value = r.devCode;   // prefill so testing is one tap
    } else { dev.hidden = true; }
    showLoginStep(2);
    setTimeout(() => $('#obOtp').focus(), 60);
  } catch (e) {
    toast('⚠️ ' + e.message);
  } finally {
    btn.disabled = false; btn.textContent = label;
  }
}
async function verifyOtp() {
  const code = ($('#obOtp').value || '').replace(/\D/g, '');
  if (code.length < 4) { toast('Enter the code'); return; }
  const btn = $('#obVerify'); const label = btn.textContent;
  btn.disabled = true; btn.textContent = 'Verifying…';
  try {
    await api('/shop/auth/verify-otp', {
      method: 'POST',
      body: JSON.stringify({ phone: pendingPhone, code, name: LS.get('hs_name') || '', referralCode: LS.get('hs_ref') || null }),
    });
    LS.set('hs_phone', pendingPhone);
    LS.set('hs_verified', '1');
    boot();
  } catch (e) {
    toast('⚠️ ' + e.message);
  } finally {
    btn.disabled = false; btn.textContent = label;
  }
}
$('#obSendOtp').addEventListener('click', () => { try { sendOtp(); } catch (e) { toast(String(e)); } });
$('#obVerify').addEventListener('click', () => { try { verifyOtp(); } catch (e) { toast(String(e)); } });
$('#otpResend').addEventListener('click', () => sendOtp());
$('#otpChange').addEventListener('click', () => { showLoginStep(1); $('#obPhone').focus(); });
['#obPhone', '#obName', '#obRef'].forEach((sel) => {
  const el = $(sel);
  if (el) el.addEventListener('keydown', (ev) => { if (ev.key === 'Enter') { ev.preventDefault(); sendOtp(); } });
});
$('#obOtp').addEventListener('keydown', (ev) => { if (ev.key === 'Enter') { ev.preventDefault(); verifyOtp(); } });

async function boot() {
  if (!store.phone) { $('#onboard').hidden = false; $('#app').hidden = true; return; }
  $('#onboard').hidden = true; $('#app').hidden = false;
  const loader = $('#appLoading'); if (loader) loader.hidden = false;
  try {
    const [menu, ctx] = await Promise.all([
      api('/shop/menu'),
      api('/shop/context?phone=' + encodeURIComponent(store.phone)).catch(() => ({ known: false })),
    ]);
    PRODUCTS = menu.products || [];
    CATS = menu.categories || [];
    setContext(ctx);
    activeCat = CATS[0] || null;
    updateDeliverAddr();
    renderHome();
    renderCartBadge();
  } catch (e) {
    toast('⚠️ Could not load — ' + e.message);
  } finally {
    if (loader) loader.hidden = true;
  }
}

function setContext(ctx) {
  ctx = ctx || {};
  CTX.wallet = ctx.wallet || 0;
  CTX.walletPending = ctx.walletPending || 0;
  CTX.address = ctx.address || LS.get('hs_addr') || '';
  CTX.name = ctx.name || store.name || '';
  CTX.referralCode = ctx.referralCode || '';
  updateDeliverAddr();
}

// --- product data helpers ----------------------------------------------------
const inStock = (p) => p.stock > 0;
const popularProducts = () => PRODUCTS.filter(inStock).slice(0, 12);
const topPicks = () => PRODUCTS.filter(inStock).slice(0, 10);
const listingProducts = () => PRODUCTS.filter((p) => p.category === activeCat);
const searchProducts = (q) => {
  const t = q.trim().toLowerCase();
  return PRODUCTS.filter((p) => p.name.toLowerCase().includes(t) || (p.category || '').toLowerCase().includes(t));
};
const catEmoji = (c) => { const it = PRODUCTS.find((p) => p.category === c); return (it && it.emoji) || '🛍️'; };
const catCount = (c) => PRODUCTS.filter((p) => p.category === c).length;

// --- card builders -----------------------------------------------------------
function addControl(p, wide) {
  const qty = store.cart[p.id] || 0;
  if (!inStock(p)) return '<button class="oos-btn" disabled>Out of stock</button>';
  if (qty > 0) return stepperHtml(p.id, qty);
  return `<button class="add-btn ${wide ? 'add-wide' : ''}" data-add="${p.id}">${wide ? 'Add to basket' : '+'}</button>`;
}
const stepperHtml = (id, qty) =>
  `<div class="stepper"><button data-dec="${id}" aria-label="less">−</button><span class="qty">${qty}</span><button data-inc="${id}" aria-label="more">+</button></div>`;

const prowHtml = (p) => `
  <div class="prow" data-prod="${p.id}">
    <div class="prow-img">${p.emoji || '🛒'}</div>
    <div class="prow-body">
      <div class="prow-name">${esc(p.name)}</div>
      <div class="prow-unit">${esc(p.unit)}</div>
      <div class="prow-price">${rupee(p.price)}</div>
    </div>
    <div class="prow-act">${addControl(p)}</div>
  </div>`;

const ptileHtml = (p) => `
  <div class="ptile" data-prod="${p.id}">
    <div class="ptile-img">${p.emoji || '🛒'}</div>
    <div class="ptile-name">${esc(p.name)}</div>
    <div class="ptile-unit">${esc(p.unit)}</div>
    <div class="ptile-foot"><span class="ptile-price">${rupee(p.price)}</span>${addControl(p)}</div>
  </div>`;

function paint(sel, list, tpl, empty) {
  const el = $(sel);
  if (!el) return;
  el.innerHTML = list.length ? list.map(tpl).join('')
    : (empty || '<p style="color:var(--muted);text-align:center;padding:40px;grid-column:1/-1">Nothing here yet.</p>');
  wireCards(el);
}

function wireCards(root) {
  root.querySelectorAll('[data-add],[data-inc]').forEach((b) =>
    b.addEventListener('click', (e) => { e.stopPropagation(); changeQty(b.dataset.add || b.dataset.inc, 1); }));
  root.querySelectorAll('[data-dec]').forEach((b) =>
    b.addEventListener('click', (e) => { e.stopPropagation(); changeQty(b.dataset.dec, -1); }));
  root.querySelectorAll('[data-prod]').forEach((c) =>
    c.addEventListener('click', () => openDetail(c.dataset.prod)));
}

function changeQty(id, delta) {
  const cart = store.cart;
  cart[id] = (cart[id] || 0) + delta;
  if (cart[id] <= 0) delete cart[id];
  store.cart = cart;
  repaintAll();
}

function repaintAll() {
  renderCartBadge();
  paint('#topPicks', topPicks(), ptileHtml);
  paint('#popularList', popularProducts(), prowHtml);
  if ($('#screen-listing').classList.contains('active')) paint('#listingList', listingProducts(), prowHtml);
  if (lastQuery) paint('#searchList', searchProducts(lastQuery), prowHtml);
  renderCart();
  if (detailId) refreshDetailAction();
  if ($('#screen-checkout').classList.contains('active')) renderCheckoutSummary();
}

// --- home --------------------------------------------------------------------
function renderHome() {
  const circ = $('#catCircles');
  if (circ) {
    circ.innerHTML = CATS.map((c) => `
      <button class="ccircle" data-opencat="${esc(c)}">
        <div class="ccircle-img">${catEmoji(c)}</div>
        <span class="ccircle-name">${esc(c)}</span>
      </button>`).join('');
    circ.querySelectorAll('[data-opencat]').forEach((b) =>
      b.addEventListener('click', () => openListing(b.dataset.opencat)));
  }
  paint('#topPicks', topPicks(), ptileHtml);
  paint('#popularList', popularProducts(), prowHtml);
}

// --- categories --------------------------------------------------------------
function renderCatGrid() {
  const g = $('#catGrid');
  g.innerHTML = CATS.map((c) => `
    <button class="ccard" data-opencat="${esc(c)}">
      <div class="ccard-img">${catEmoji(c)}</div>
      <div class="ccard-name">${esc(c)}</div>
      <div class="ccard-count">${catCount(c)} item${catCount(c) === 1 ? '' : 's'}</div>
    </button>`).join('') || '<p style="color:var(--muted);grid-column:1/-1;text-align:center;padding:40px">No categories yet.</p>';
  g.querySelectorAll('[data-opencat]').forEach((b) =>
    b.addEventListener('click', () => openListing(b.dataset.opencat)));
}

// --- listing -----------------------------------------------------------------
function openListing(cat) {
  activeCat = cat;
  renderListing();
  showScreen('listing');
}
function renderListing() {
  $('#listingTitle').textContent = activeCat || 'Products';
  const chips = $('#listingChips');
  chips.innerHTML = CATS.map((c) =>
    `<button class="chip ${c === activeCat ? 'active' : ''}" data-chip="${esc(c)}">${esc(c)}</button>`).join('');
  chips.querySelectorAll('[data-chip]').forEach((b) =>
    b.addEventListener('click', () => { activeCat = b.dataset.chip; renderListing(); window.scrollTo(0, 0); }));
  paint('#listingList', listingProducts(), prowHtml, '<p style="color:var(--muted);text-align:center;padding:40px">No items in this category.</p>');
}

// --- search ------------------------------------------------------------------
$('#searchInput').addEventListener('input', (e) => {
  const q = e.target.value;
  lastQuery = q;
  if (!q.trim()) { if ($('#screen-search').classList.contains('active')) showScreen('home'); return; }
  $('#searchTitle').textContent = 'Results for “' + q.trim() + '”';
  paint('#searchList', searchProducts(q), prowHtml, '<p style="color:var(--muted);text-align:center;padding:40px">No matches — try another word.</p>');
  if (!$('#screen-search').classList.contains('active')) showScreen('search');
});

// --- cart / basket -----------------------------------------------------------
function cartLines() {
  const cart = store.cart;
  return Object.entries(cart).map(([id, qty]) => {
    const p = PRODUCTS.find((x) => x.id === id);
    return p ? { ...p, qty } : null;
  }).filter(Boolean);
}
const cartTotal = () => cartLines().reduce((s, l) => s + l.price * l.qty, 0);

function renderCartBadge() {
  const n = Object.values(store.cart).reduce((a, b) => a + b, 0);
  ['#cartBadge', '#cartBadgeTop'].forEach((sel) => {
    const b = $(sel); if (b) { b.textContent = n; b.hidden = !n; }
  });
}

function renderCart() {
  const lines = cartLines();
  renderCartBadge();
  if (!lines.length) {
    $('#cartItems').innerHTML = '<div class="cart-empty">🧺 Your basket is empty.<br>Add some fresh groceries!</div>';
    $('#basketFoot').hidden = true;
    return;
  }
  $('#cartItems').innerHTML = lines.map((l) => `
    <div class="cart-item">
      <div class="ci-img">${l.emoji || '🛒'}</div>
      <div class="ci-info"><div class="ci-name">${esc(l.name)}</div><div class="ci-price">${rupee(l.price)}/${esc(l.unit)} · ${rupee(l.price * l.qty)}</div></div>
      ${stepperHtml(l.id, l.qty)}
    </div>`).join('');
  wireCards($('#cartItems'));
  $('#basketFoot').hidden = false;
  const total = cartTotal();
  $('#basketItemTotal').textContent = rupee(total);
  $('#basketTotal').textContent = rupee(total);
  const banner = $('#savingBanner');
  if (CTX.wallet > 0) { banner.hidden = false; banner.textContent = `👛 ${rupee(CTX.wallet)} wallet credit available — use at checkout`; }
  else { banner.hidden = false; banner.textContent = '🎉 Free delivery on this order'; }
}

$('#toCheckout').addEventListener('click', () => showScreen('checkout'));

// --- checkout ----------------------------------------------------------------
function renderCheckout() {
  $('#ckName').value = $('#ckName').value || store.name || '';
  $('#ckAddress').value = $('#ckAddress').value || CTX.address || '';
  const wr = $('#walletRow');
  wr.hidden = CTX.wallet <= 0;
  $('#walletAvail').textContent = rupee(CTX.wallet);
  renderCheckoutSummary();
}
function renderCheckoutSummary() {
  const gross = cartTotal();
  const useW = $('#useWallet').checked && CTX.wallet > 0;
  const wUsed = useW ? Math.min(CTX.wallet, gross) : 0;
  $('#sumItemTotal').textContent = rupee(gross);
  $('#sumWalletRow').hidden = wUsed <= 0;
  $('#sumWallet').textContent = '−' + rupee(wUsed);
  $('#sumTotal').textContent = rupee(Math.max(0, gross - wUsed));
}
$('#useWallet').addEventListener('change', renderCheckoutSummary);

// slot + payment selectors
$('#slotRow').querySelectorAll('.slot').forEach((s) =>
  s.addEventListener('click', () => { $('#slotRow').querySelectorAll('.slot').forEach((x) => x.classList.remove('active')); s.classList.add('active'); }));
[['#payOptUpi', 'upi'], ['#payOptCod', 'cod']].forEach(([sel]) => {
  $(sel).addEventListener('click', () => {
    document.querySelectorAll('.pay-opt').forEach((o) => o.classList.remove('active'));
    $(sel).classList.add('active');
    $(sel).querySelector('input').checked = true;
  });
});

$('#placeOrder').addEventListener('click', async () => {
  const lines = cartLines();
  if (!lines.length) { toast('Your basket is empty'); showScreen('cart'); return; }
  const name = $('#ckName').value.trim();
  const address = $('#ckAddress').value.trim();
  if (address.length < 5) { toast('Please enter your delivery address'); $('#ckAddress').focus(); return; }
  const payment = document.querySelector('input[name="pay"]:checked').value;
  const btn = $('#placeOrder');
  btn.disabled = true; btn.textContent = 'Placing…';
  try {
    const r = await api('/shop/checkout', {
      method: 'POST',
      body: JSON.stringify({
        phone: store.phone, name: name || store.name, address,
        items: lines.map((l) => ({ productId: l.id, qty: l.qty })),
        paymentMode: payment, useWallet: $('#useWallet').checked,
        referralCode: LS.get('hs_ref') || null,
      }),
    });
    if (name) LS.set('hs_name', name);
    CTX.address = $('#ckAddress').value.trim();
    LS.set('hs_addr', CTX.address);
    updateDeliverAddr();
    store.cart = {};
    LS.remove('hs_ref');
    const ctx = await api('/shop/context?phone=' + encodeURIComponent(store.phone)).catch(() => ({}));
    CTX.wallet = ctx.wallet || 0;
    CTX.walletPending = ctx.walletPending || 0;
    renderCart();
    showConfirm(r);
  } catch (e) {
    toast('⚠️ ' + e.message);
  } finally {
    btn.disabled = false; btn.textContent = 'Place order →';
  }
});

function showConfirm(r) {
  $('#confirmCard').innerHTML = `
    <div class="confirm-emoji">✅</div>
    <h2>Order placed!</h2>
    <div class="confirm-line">Order <b>${esc(r.code)}</b></div>
    ${r.walletUsed ? `<div class="confirm-line">👛 Wallet applied −${rupee(r.walletUsed)}</div>` : ''}
    <div class="confirm-line" style="font-size:19px;font-weight:800;color:#fff">${r.total <= 0 ? 'Fully paid with wallet 🎉' : 'To pay ' + rupee(r.total)}</div>
    ${r.paymentMode === 'upi' && r.upiLink ? `<a class="confirm-upi" href="${r.upiLink}">📲 Pay ${rupee(r.total)} via UPI</a>` : ''}
    ${r.paymentMode === 'cod' && r.total > 0 ? `<div class="confirm-line">💵 Pay ${rupee(r.total)} cash on delivery</div>` : ''}
    ${r.loyalty ? `<div class="confirm-loyalty">🎁 You'll earn ${rupee(r.loyalty)} cashback after delivery!</div>` : ''}
    <div class="confirm-line">🧺 We're preparing your order — you'll get updates as it ships &amp; arrives.</div>
    <button class="btn-lime" style="margin-top:14px" id="confirmDone">Track my orders</button>`;
  $('#confirm').hidden = false;
  $('#confirmDone').addEventListener('click', () => { $('#confirm').hidden = true; showScreen('orders'); });
}

// --- orders ------------------------------------------------------------------
async function renderOrders() {
  const list = $('#orderList');
  list.innerHTML = '<div class="cart-empty">Loading…</div>';
  try {
    const orders = await api('/shop/orders?phone=' + encodeURIComponent(store.phone));
    list.innerHTML = orders.map((o) => `
      <div class="order">
        <div class="order-top"><span class="order-code">${esc(o.code)}</span><span class="badge b-${o.status}">${esc(o.status.replace(/_/g, ' '))}</span></div>
        <div class="order-items">${o.items.map((l) => `${l.emoji || '🛒'}×${l.qty}`).join(' ')}</div>
        <div class="order-foot"><span>${new Date(o.createdAt).toLocaleString()}</span><b>${rupee(o.total)} · ${(o.paymentMode || '').toUpperCase()}</b></div>
      </div>`).join('') || '<div class="cart-empty">No orders yet — place your first! 🍎</div>';
  } catch (e) {
    list.innerHTML = '<div class="cart-empty">⚠️ Could not load orders.<br>' + esc(e.message) + '</div>';
  }
}

// --- profile / account -------------------------------------------------------
async function renderProfile() {
  const nm = (CTX.name || store.name || '').trim();
  $('#pfName').textContent = nm || 'Guest';
  $('#pfPhone').textContent = store.phone ? '+' + store.phone : '—';
  $('#pfAvatar').textContent = nm ? nm[0].toUpperCase() : '👤';
  $('#pfWallet').textContent = rupee(CTX.wallet);
  $('#pfPending').textContent = rupee(CTX.walletPending);
  const refCard = $('#pfReferralCard');
  if (CTX.referralCode) { refCard.hidden = false; $('#pfRefCode').textContent = CTX.referralCode; }
  else refCard.hidden = true;
  try {
    const o = await api('/shop/orders?phone=' + encodeURIComponent(store.phone));
    $('#pfOrders').textContent = o.length;
  } catch { $('#pfOrders').textContent = '—'; }
}

$('#pfEdit').addEventListener('click', () => $('#deliverRow').click());
$('#pfAddress').addEventListener('click', () => $('#deliverRow').click());
$('#pfShare').addEventListener('click', async () => {
  const code = CTX.referralCode;
  if (!code) return;
  const msg = `Order fresh groceries on HSFOODS! 🍃 Use my code ${code} and we both earn cashback.\n${location.origin}/shop.html`;
  if (navigator.share) { try { await navigator.share({ title: 'HSFOODS', text: msg }); } catch {} }
  else { try { await navigator.clipboard.writeText(msg); toast('Referral copied ✓'); } catch { toast('Your code: ' + code); } }
});
$('#pfLogout').addEventListener('click', () => {
  ['hs_phone', 'hs_verified', 'hs_name', 'hs_ref', 'hs_addr', 'hs_cart'].forEach((k) => LS.remove(k));
  location.reload();
});

// --- product detail ----------------------------------------------------------
function openDetail(id) {
  const p = PRODUCTS.find((x) => x.id === id);
  if (!p) return;
  detailId = id;
  $('#detailCard').innerHTML = `
    <div class="dt-top"><button class="dt-close" id="dtClose">✕</button></div>
    <div class="dt-hero">${p.emoji || '🛒'}</div>
    <div class="dt-name">${esc(p.name)}</div>
    <div class="dt-unit">${esc(p.unit)} · ${inStock(p) ? 'In stock' : 'Out of stock'}</div>
    <div class="dt-price">${rupee(p.price)}<span>/${esc(p.unit)}</span></div>
    <div class="dt-sec">Product details</div>
    <div class="dt-body">Fresh ${esc(p.name.toLowerCase())}, hand-picked daily and delivered fast. Pay by UPI or cash and earn cashback on every order.</div>
    <div class="dt-bar">
      <div style="flex:1"><div style="font-size:12px;color:var(--muted)">Price</div><div style="font-size:20px;font-weight:800">${rupee(p.price)}</div></div>
      <span id="dtAction">${addControl(p, true)}</span>
    </div>`;
  wireCards($('#detailCard'));
  $('#dtClose').addEventListener('click', closeDetail);
  $('#detail').hidden = false;
}
function refreshDetailAction() {
  const p = PRODUCTS.find((x) => x.id === detailId);
  const slot = $('#dtAction');
  if (!p || !slot) return;
  slot.innerHTML = addControl(p, true);
  wireCards($('#detailCard'));
}
function closeDetail() { $('#detail').hidden = true; detailId = null; }

// --- address -----------------------------------------------------------------
function updateDeliverAddr() {
  const el = $('#deliverAddr');
  el.textContent = CTX.address ? CTX.address : 'Set your delivery address ›';
}
$('#deliverRow').addEventListener('click', () => {
  $('#addrName').value = store.name || '';
  $('#addrInput').value = CTX.address || '';
  $('#addrModal').hidden = false;
});
$('#addrCancel').addEventListener('click', () => { $('#addrModal').hidden = true; });
$('#addrSave').addEventListener('click', () => {
  const addr = $('#addrInput').value.trim();
  const nm = $('#addrName').value.trim();
  if (addr.length < 5) { toast('Please enter a valid address'); return; }
  CTX.address = addr; LS.set('hs_addr', addr);
  if (nm) { LS.set('hs_name', nm); CTX.name = nm; }
  $('#ckAddress').value = addr; $('#ckName').value = nm || store.name || '';
  updateDeliverAddr();
  $('#addrModal').hidden = true;
  toast('Saved ✓');
  if ($('#screen-profile').classList.contains('active')) renderProfile();
});

// --- navigation --------------------------------------------------------------
const NAV_FOR = { home: 'home', categories: 'categories', cart: 'cart', orders: 'orders', profile: 'profile', listing: 'categories', search: 'home', checkout: 'cart' };
function showScreen(name) {
  document.querySelectorAll('.screen').forEach((s) => s.classList.toggle('active', s.id === 'screen-' + name));
  const tab = NAV_FOR[name] || name;
  document.querySelectorAll('.nav-btn').forEach((b) => b.classList.toggle('active', b.dataset.screen === tab));
  if (name === 'home') renderHome();
  if (name === 'categories') renderCatGrid();
  if (name === 'cart') renderCart();
  if (name === 'checkout') renderCheckout();
  if (name === 'orders') renderOrders();
  if (name === 'profile') renderProfile();
  window.scrollTo(0, 0);
}
document.querySelectorAll('[data-screen]').forEach((b) => b.addEventListener('click', () => showScreen(b.dataset.screen)));
document.querySelectorAll('[data-back]').forEach((b) => b.addEventListener('click', () => showScreen(b.dataset.back)));
$('#cartIconTop').addEventListener('click', () => showScreen('cart'));
$('#notifBtn').addEventListener('click', () => toast("You're all caught up ✨"));

// --- start -------------------------------------------------------------------
boot();
if ('serviceWorker' in navigator) {
  const hadController = !!navigator.serviceWorker.controller;
  navigator.serviceWorker.register('/sw.js').catch(() => {});
  let reloaded = false;
  navigator.serviceWorker.addEventListener('controllerchange', () => {
    if (reloaded || !hadController) return;
    reloaded = true; location.reload();
  });
}
