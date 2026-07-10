const $ = (s) => document.querySelector(s);
const api = async (path, opts) => {
  const res = await fetch('/api' + path, { headers: { 'Content-Type': 'application/json' }, ...opts });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.statusText);
  return res.json();
};
const rupee = (n) => '₹' + Number(n || 0).toLocaleString('en-IN', { maximumFractionDigits: 2 });

// --- state -------------------------------------------------------------------
// Storage wrapper: falls back to in-memory when localStorage is blocked
// (private mode / strict privacy settings), so the app never crashes.
const _mem = {};
const LS = {
  get(k) { try { return localStorage.getItem(k); } catch { return k in _mem ? _mem[k] : null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { _mem[k] = v; } },
  remove(k) { try { localStorage.removeItem(k); } catch { delete _mem[k]; } },
};
const store = {
  get phone() { return LS.get('hs_phone') || ''; },
  get name() { return LS.get('hs_name') || ''; },
  get cart() { try { return JSON.parse(LS.get('hs_cart') || '{}'); } catch { return {}; } },
  set cart(c) { LS.set('hs_cart', JSON.stringify(c)); },
};
let PRODUCTS = [];
let CATS = [];
let CTX = { wallet: 0, address: '' };
let activeCat = null;

function toast(msg) {
  const t = $('#toast'); t.textContent = msg; t.classList.add('show');
  clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.remove('show'), 1800);
}

// --- onboarding --------------------------------------------------------------
$('#obStart').addEventListener('click', () => {
  const phone = $('#obPhone').value.replace(/\D/g, '');
  if (phone.length < 8) { toast('Enter a valid number'); return; }
  LS.set('hs_phone', phone);
  if ($('#obName').value.trim()) LS.set('hs_name', $('#obName').value.trim());
  if ($('#obRef').value.trim()) LS.set('hs_ref', $('#obRef').value.trim());
  boot();
});

async function boot() {
  if (!store.phone) { $('#onboard').hidden = false; $('#app').hidden = true; return; }
  // show the app shell first so onboarding can never get "stuck" on errors
  $('#onboard').hidden = true; $('#app').hidden = false;
  try {
    const [menu, ctx] = await Promise.all([
      api('/shop/menu'),
      api('/shop/context?phone=' + encodeURIComponent(store.phone)).catch(() => ({ known: false })),
    ]);
    PRODUCTS = menu.products;
    CATS = menu.categories;
    CTX.wallet = ctx.wallet || 0;
    CTX.address = ctx.address || '';
    renderWallet();
    renderCats(CATS);
    renderProducts();
    renderHome();
    renderCart();
  } catch (e) {
    toast('⚠️ Could not load — ' + e.message);
  }
}

function renderWallet() { $('#walletChip').textContent = '👛 ' + rupee(CTX.wallet); }

// --- shop --------------------------------------------------------------------
function renderCats(cats) {
  activeCat = activeCat && cats.includes(activeCat) ? activeCat : (cats[0] || null);
  $('#shopCats').innerHTML = cats.map((c) =>
    `<button class="cat-chip ${c === activeCat ? 'active' : ''}" data-cat="${c}">${c}</button>`).join('');
  document.querySelectorAll('.cat-chip').forEach((b) =>
    b.addEventListener('click', () => { activeCat = b.dataset.cat; renderCats(cats); renderProducts(); }));
}

const prodCardHtml = (p) => {
  const qty = store.cart[p.id] || 0;
  const oos = p.stock <= 0;
  return `
    <div class="prod ${oos ? 'oos' : ''}">
      <div class="prod-emoji">${p.emoji}</div>
      <div class="prod-name">${p.name}</div>
      <div class="prod-price">${rupee(p.price)}<span>/${p.unit}</span></div>
      <div class="prod-add">${oos ? '<div class="add-btn" style="opacity:.6">Out of stock</div>'
        : qty > 0 ? stepperHtml(p.id, qty) : `<button class="add-btn" data-add="${p.id}">Add +</button>`}</div>
    </div>`;
};

function renderProducts() {
  const list = PRODUCTS.filter((p) => p.category === activeCat);
  const grid = $('#prodGrid');
  grid.innerHTML = list.map(prodCardHtml).join('') ||
    '<p style="grid-column:1/-1;text-align:center;color:var(--muted);padding:40px">No items here.</p>';
  wireQty(grid);
}

const stepperHtml = (id, qty) =>
  `<div class="stepper"><button data-dec="${id}">−</button><span class="qty">${qty}</span><button data-inc="${id}">+</button></div>`;

function wireQty(root = document) {
  root.querySelectorAll('[data-add],[data-inc]').forEach((b) =>
    b.addEventListener('click', () => changeQty(b.dataset.add || b.dataset.inc, 1)));
  root.querySelectorAll('[data-dec]').forEach((b) =>
    b.addEventListener('click', () => changeQty(b.dataset.dec, -1)));
}

function changeQty(id, delta) {
  const cart = store.cart;
  cart[id] = (cart[id] || 0) + delta;
  if (cart[id] <= 0) delete cart[id];
  store.cart = cart;
  renderProducts();
  renderFeatured();
  renderCartBadge();
  if (currentScreen() === 'cart') renderCart();
}

// --- home (landing) ----------------------------------------------------------
function renderHome() {
  const showcase = $('#catShowcase');
  if (!showcase) return;   // resilient if an old cached HTML is missing the section
  // category showcase — one tile per category with a representative emoji
  showcase.innerHTML = CATS.map((c) => {
    const items = PRODUCTS.filter((p) => p.category === c);
    const emoji = (items[0] && items[0].emoji) || '🛍️';
    return `<button class="cat-tile" data-shopcat="${c}">
      <div class="cat-tile-emoji">${emoji}</div>
      <div class="cat-tile-name">${c}</div>
      <div class="cat-tile-count">${items.length} item${items.length === 1 ? '' : 's'}</div>
    </button>`;
  }).join('');
  document.querySelectorAll('[data-shopcat]').forEach((b) =>
    b.addEventListener('click', () => { activeCat = b.dataset.shopcat; renderCats(CATS); renderProducts(); showScreen('shop'); }));
  renderFeatured();
}

function renderFeatured() {
  const grid = $('#featuredGrid');
  if (!grid) return;
  const list = PRODUCTS.filter((p) => p.stock > 0).slice(0, 8);
  grid.innerHTML = list.map(prodCardHtml).join('');
  wireQty(grid);
}

// --- cart --------------------------------------------------------------------
function cartLines() {
  const cart = store.cart;
  return Object.entries(cart).map(([id, qty]) => {
    const p = PRODUCTS.find((x) => x.id === id);
    return p ? { ...p, qty } : null;
  }).filter(Boolean);
}
function cartTotal() { return cartLines().reduce((s, l) => s + l.price * l.qty, 0); }

function renderCartBadge() {
  const n = Object.values(store.cart).reduce((a, b) => a + b, 0);
  ['#cartBadge', '#cartBadgeTop'].forEach((sel) => {
    const badge = $(sel);
    if (badge) { badge.textContent = n; badge.hidden = !n; }
  });
}

function renderCart() {
  const lines = cartLines();
  renderCartBadge();
  if (!lines.length) {
    $('#cartItems').innerHTML = '<div class="cart-empty">🧺 Your basket is empty.<br>Add some fresh fruits!</div>';
    $('#checkoutBox').hidden = true;
    return;
  }
  $('#cartItems').innerHTML = lines.map((l) => `
    <div class="cart-item">
      <div class="ci-emoji">${l.emoji}</div>
      <div class="ci-info"><div class="ci-name">${l.name}</div><div class="ci-price">${rupee(l.price)}/${l.unit} · ${rupee(l.price * l.qty)}</div></div>
      ${stepperHtml(l.id, l.qty)}
    </div>`).join('');
  wireQty();
  $('#checkoutBox').hidden = false;
  $('#cartTotal').textContent = rupee(cartTotal());
  $('#walletRow').hidden = CTX.wallet <= 0;
  $('#walletAvail').textContent = rupee(CTX.wallet);
  if (CTX.address && !$('#ckAddress').value) $('#ckAddress').value = CTX.address;
}

$('#placeOrder').addEventListener('click', async () => {
  const lines = cartLines();
  if (!lines.length) return;
  const address = $('#ckAddress').value.trim();
  if (address.length < 5) { toast('Please enter your delivery address'); return; }
  const payment = document.querySelector('input[name="pay"]:checked').value;
  $('#placeOrder').disabled = true; $('#placeOrder').textContent = 'Placing…';
  try {
    const r = await api('/shop/checkout', {
      method: 'POST',
      body: JSON.stringify({
        phone: store.phone, name: store.name, address,
        items: lines.map((l) => ({ productId: l.id, qty: l.qty })),
        paymentMode: payment, useWallet: $('#useWallet').checked,
        referralCode: LS.get('hs_ref') || null,
      }),
    });
    store.cart = {}; renderCart(); renderProducts();
    LS.remove('hs_ref');
    // refresh wallet after redemption
    const ctx = await api('/shop/context?phone=' + encodeURIComponent(store.phone)).catch(() => ({}));
    CTX.wallet = ctx.wallet || 0; renderWallet();
    showConfirm(r);
  } catch (e) {
    toast('⚠️ ' + e.message);
  } finally {
    $('#placeOrder').disabled = false; $('#placeOrder').textContent = 'Place order';
  }
});

function showConfirm(r) {
  const c = $('#confirmCard');
  c.innerHTML = `
    <div class="confirm-emoji">✅</div>
    <h2>Order placed!</h2>
    <div class="confirm-line">Order <b>${r.code}</b></div>
    ${r.walletUsed ? `<div class="confirm-line">👛 Wallet applied −${rupee(r.walletUsed)}</div>` : ''}
    <div class="confirm-line" style="font-size:20px;font-weight:800;color:var(--ink)">${r.total <= 0 ? 'Fully paid with wallet 🎉' : 'To pay ' + rupee(r.total)}</div>
    ${r.paymentMode === 'upi' && r.upiLink ? `<a class="confirm-upi" href="${r.upiLink}">📲 Pay ${rupee(r.total)} via UPI</a>` : ''}
    ${r.paymentMode === 'cod' && r.total > 0 ? `<div class="confirm-line">💵 Pay ${rupee(r.total)} cash on delivery</div>` : ''}
    ${r.loyalty ? `<div class="confirm-loyalty">🎁 You'll earn ${rupee(r.loyalty)} cashback after delivery!</div>` : ''}
    <div class="confirm-line">🚚 Out for delivery in ~10 minutes</div>
    <button class="btn-primary" style="margin-top:14px" id="confirmDone">Track my orders</button>`;
  $('#confirm').hidden = false;
  $('#confirmDone').addEventListener('click', () => { $('#confirm').hidden = true; showScreen('orders'); });
}

// --- orders ------------------------------------------------------------------
async function renderOrders() {
  const orders = await api('/shop/orders?phone=' + encodeURIComponent(store.phone));
  $('#orderList').innerHTML = orders.map((o) => `
    <div class="order">
      <div class="order-top"><span class="order-code">${o.code}</span><span class="badge b-${o.status}">${o.status.replace(/_/g, ' ')}</span></div>
      <div class="order-items">${o.items.map((l) => `${l.emoji}×${l.qty}`).join(' ')}</div>
      <div class="order-foot"><span>${new Date(o.createdAt).toLocaleString()}</span><b>${rupee(o.total)} · ${(o.paymentMode || '').toUpperCase()}</b></div>
    </div>`).join('') || '<div class="cart-empty">No orders yet — place your first! 🍎</div>';
}

// --- navigation --------------------------------------------------------------
const currentScreen = () => document.querySelector('.nav-btn.active')?.dataset.screen || 'home';
function showScreen(name) {
  document.querySelectorAll('.nav-btn').forEach((b) => b.classList.toggle('active', b.dataset.screen === name));
  document.querySelectorAll('.screen').forEach((s) => s.classList.toggle('active', s.id === 'screen-' + name));
  if (name === 'home') renderHome();
  if (name === 'cart') renderCart();
  if (name === 'orders') renderOrders();
  window.scrollTo(0, 0);
}
// wire nav buttons + any element with data-screen (hero CTA, "see all" links)
document.querySelectorAll('[data-screen]').forEach((b) => b.addEventListener('click', () => showScreen(b.dataset.screen)));
$('#walletChip').addEventListener('click', () => showScreen('orders'));

// --- start -------------------------------------------------------------------
boot();
// Recover from any previously-installed service worker (stale cache). We do NOT
// register a new SW here — we only nudge an EXISTING one to update, so the
// kill-switch sw.js runs, clears caches, unregisters and reloads. Fresh
// browsers have no registration, so nothing happens (no loop, plain website).
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.getRegistration().then((r) => { if (r) r.update(); }).catch(() => {});
}
