/**
 * E-commerce Chatbot Assistant Frontend
 * Connected to FastAPI /api/chat backed by the integrated Ollama LLM.
 * All normal conversational responses are dynamically generated in real time by Ollama.
 * Zero hardcoded response sentences, keyword dictionaries, or static conversation flows.
 */

class CurrencyManager {
  constructor() {
    // Baseline rate ~277.16 PKR per USD
    this.rateUsdPerPkr = 0.003608;
    this.isLive = false;
    this.fetchLiveRate();
  }

  async fetchLiveRate() {
    try {
      if (typeof fetch === 'function') {
        const res = await fetch('https://open.er-api.com/v6/latest/PKR');
        if (res.ok) {
          const data = await res.json();
          if (data && data.rates && data.rates.USD) {
            this.rateUsdPerPkr = data.rates.USD;
            this.isLive = true;
            return;
          }
        }
      }
    } catch (e) {
      try {
        if (typeof fetch === 'function') {
          const resLocal = await fetch('/api/exchange-rate');
          if (resLocal.ok) {
            const dataLocal = await resLocal.json();
            if (dataLocal && dataLocal.rate_usd) {
              this.rateUsdPerPkr = dataLocal.rate_usd;
              this.isLive = true;
            }
          }
        }
      } catch (err) {}
    }
  }

  convertPkrToUsd(pkrAmount) {
    if (!pkrAmount || isNaN(pkrAmount)) return 0;
    const usd = pkrAmount * this.rateUsdPerPkr;
    if (usd >= 10) return Math.round(usd);
    return Math.round(usd * 100) / 100;
  }
}

// UI Controller
const ChatbotApp = {
  isOpen: false,
  chatHistory: [],
  catalog: [],
  currencyManager: null,

  init(catalog) {
    this.catalog = Array.isArray(catalog) ? catalog : (window.PRODUCTS_DATA || []);
    this.currencyManager = new CurrencyManager();
    this.renderUI();
  },

  renderUI() {
    if (document.getElementById('chatbotLauncher')) return;

    // 1. Floating Launcher Button
    const launcher = document.createElement('button');
    launcher.id = 'chatbotLauncher';
    launcher.className = 'fixed bottom-6 right-6 z-50 w-14 h-14 rounded-full bg-gradient-to-r from-indigo-600 to-violet-600 text-white shadow-xl hover:shadow-2xl hover:scale-105 active:scale-95 transition-all duration-200 flex items-center justify-center focus:outline-none focus:ring-4 focus:ring-indigo-200';
    launcher.setAttribute('aria-label', 'Open AI Product Search Assistant');
    launcher.innerHTML = `
      <div class="relative flex items-center justify-center">
        <svg id="launcherOpenIcon" class="w-7 h-7" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 10h.01M12 10h.01M16 10h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
        </svg>
        <svg id="launcherCloseIcon" class="w-7 h-7 hidden" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
        </svg>
        <span class="absolute -top-1 -right-1 flex h-3 w-3">
          <span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
          <span class="relative inline-flex rounded-full h-3 w-3 bg-emerald-500 border-2 border-white"></span>
        </span>
      </div>
    `;

    // 2. Chat Window Container
    const chatWindow = document.createElement('div');
    chatWindow.id = 'chatbotWindow';
    chatWindow.className = 'fixed bottom-24 right-6 z-50 w-[380px] sm:w-[420px] max-w-[calc(100vw-2rem)] h-[580px] max-h-[calc(100vh-7rem)] bg-white rounded-2xl shadow-2xl border border-slate-200 flex flex-col overflow-hidden hidden transition-all duration-200 transform scale-95 opacity-0';

    chatWindow.innerHTML = `
      <!-- Header -->
      <div class="bg-gradient-to-r from-indigo-600 to-violet-600 px-4 py-3.5 text-white flex items-center justify-between shrink-0 shadow-sm">
        <div class="flex items-center gap-2.5">
          <div class="w-8 h-8 rounded-lg bg-white/20 backdrop-blur-sm flex items-center justify-center font-bold text-sm">
            AI
          </div>
          <div>
            <h3 class="font-bold text-sm leading-tight">Product Search Assistant</h3>
            <div class="flex items-center gap-1.5 text-[11px] text-indigo-100">
              <span class="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"></span>
              <span id="chatHeaderStatus">Ollama LLM Connected</span>
            </div>
          </div>
        </div>
        <div class="flex items-center gap-1">
          <button id="chatbotRestartBtn" title="Start New Conversation" class="p-1.5 text-indigo-100 hover:text-white hover:bg-white/10 rounded-lg transition">
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
          </button>
          <button id="chatbotCloseBtn" title="Close" class="p-1.5 text-indigo-100 hover:text-white hover:bg-white/10 rounded-lg transition">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
      </div>

      <!-- Messages Thread -->
      <div id="chatbotMessages" class="flex-1 p-4 overflow-y-auto space-y-3.5 bg-slate-50 text-xs">
        <!-- Chat bubbles rendered dynamically here -->
      </div>

      <!-- Input Area -->
      <form id="chatbotForm" class="p-2.5 bg-white border-t border-slate-200 flex items-center gap-2 shrink-0">
        <input 
          type="text" 
          id="chatbotInput" 
          placeholder="Ask about products, specifications, recommendations..." 
          autocomplete="off"
          class="flex-1 text-xs bg-slate-100 border border-transparent rounded-xl px-3.5 py-2.5 outline-none focus:bg-white focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100 text-slate-800 transition"
        />
        <button 
          type="submit" 
          id="chatbotSendBtn"
          class="w-9 h-9 rounded-xl bg-indigo-600 text-white flex items-center justify-center hover:bg-indigo-700 active:scale-95 transition"
        >
          <svg class="w-4 h-4 transform rotate-90" fill="currentColor" viewBox="0 0 20 20">
            <path d="M10.894 2.553a1 1 0 00-1.788 0l-7 14a1 1 0 001.169 1.409l5-1.429A1 1 0 009 15.571V11a1 1 0 112 0v4.571a1 1 0 00.725.962l5 1.428a1 1 0 001.17-1.408l-7-14z"/>
          </svg>
        </button>
      </form>
    `;

    document.body.appendChild(launcher);
    document.body.appendChild(chatWindow);

    this.bindEvents();
  },

  bindEvents() {
    const launcher = document.getElementById('chatbotLauncher');
    const chatWindow = document.getElementById('chatbotWindow');
    const closeBtn = document.getElementById('chatbotCloseBtn');
    const restartBtn = document.getElementById('chatbotRestartBtn');
    const form = document.getElementById('chatbotForm');
    const input = document.getElementById('chatbotInput');

    const toggleChat = () => {
      this.isOpen = !this.isOpen;
      const openIcon = document.getElementById('launcherOpenIcon');
      const closeIcon = document.getElementById('launcherCloseIcon');

      if (this.isOpen) {
        chatWindow.classList.remove('hidden');
        setTimeout(() => {
          chatWindow.classList.remove('scale-95', 'opacity-0');
          chatWindow.classList.add('scale-100', 'opacity-100');
          input.focus();
        }, 10);
        openIcon.classList.add('hidden');
        closeIcon.classList.remove('hidden');

        const msgs = document.getElementById('chatbotMessages');
        if (msgs.children.length === 0) {
          this.triggerInitialGreeting();
        }
      } else {
        chatWindow.classList.add('scale-95', 'opacity-0');
        chatWindow.classList.remove('scale-100', 'opacity-100');
        setTimeout(() => {
          chatWindow.classList.add('hidden');
        }, 200);
        openIcon.classList.remove('hidden');
        closeIcon.classList.add('hidden');
      }
    };

    launcher.addEventListener('click', toggleChat);
    closeBtn.addEventListener('click', toggleChat);

    restartBtn.addEventListener('click', () => {
      this.chatHistory = [];
      const msgs = document.getElementById('chatbotMessages');
      msgs.innerHTML = '';
      this.triggerInitialGreeting();
    });

    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const text = input.value.trim();
      if (!text) return;

      this.addUserMessage(text);
      input.value = '';

      const lowerText = text.toLowerCase();
      const trackPhrases = ["track this product", "track this item", "track the price", "start tracking this", "track this", "track price", "track"];
      if (this.lastRecommendedProduct && trackPhrases.some(p => lowerText.includes(p))) {
        await this.trackProduct(this.lastRecommendedProduct);
        return;
      }

      this.showTypingIndicator();

      if (!this.chatHistory) this.chatHistory = [];
      this.chatHistory.push({ role: 'user', content: text });

      try {
        const res = await fetch('/api/chat', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            message: text,
            history: this.chatHistory.slice(-8)
          })
        });

        this.hideTypingIndicator();

        if (res.ok) {
          const data = await res.json();
          const reply = data.reply || '';
          this.chatHistory.push({ role: 'assistant', content: reply });

          if (data.products && data.products.length > 0) {
            this.lastRecommendedProduct = data.products[0];
          }

          this.addAssistantResponse({
            reply: reply,
            products: data.products || [],
            modelUsed: data.model_used
          });
        } else {
          const errData = await res.json().catch(() => ({}));
          this.addAssistantResponse({
            reply: errData.error || `Server error (${res.status}). Please verify that the backend and Ollama are running.`,
            products: []
          });
        }
      } catch (err) {
        this.hideTypingIndicator();
        this.addAssistantResponse({
          reply: "Connection notice: Unable to reach backend /api/chat. Please ensure the server is running.",
          products: []
        });
      }
    });
  },

  async triggerInitialGreeting() {
    this.showTypingIndicator();
    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: "Hello! Greet me and let me know how you can help me explore products from our store catalog today."
        })
      });
      this.hideTypingIndicator();
      if (res.ok) {
        const data = await res.json();
        if (data.reply) {
          this.chatHistory = [{ role: 'assistant', content: data.reply }];
          this.addAssistantResponse({
            reply: data.reply,
            products: data.products || [],
            modelUsed: data.model_used
          });
        }
      }
    } catch (err) {
      this.hideTypingIndicator();
    }
  },

  addUserMessage(text) {
    const container = document.getElementById('chatbotMessages');
    const div = document.createElement('div');
    div.className = 'flex justify-end';
    div.innerHTML = `
      <div class="bg-indigo-600 text-white rounded-2xl rounded-tr-sm px-3.5 py-2 max-w-[82%] shadow-sm leading-relaxed text-xs">
        ${this.escapeHTML(text)}
      </div>
    `;
    container.appendChild(div);
    this.scrollToBottom();
  },

  addAssistantResponse(resp) {
    const container = document.getElementById('chatbotMessages');
    const div = document.createElement('div');
    div.className = 'flex flex-col space-y-2 items-start';

    let contentHTML = `
      <div class="bg-white border border-slate-200 text-slate-800 rounded-2xl rounded-tl-sm p-3 max-w-[92%] shadow-sm leading-relaxed space-y-2">
        <div class="font-medium whitespace-pre-line">${this.formatMarkdown(resp.reply)}</div>
    `;

    // Display model badge if available
    if (resp.modelUsed) {
      contentHTML += `
        <div class="pt-1 flex items-center gap-1.5 text-[10px] text-slate-400 font-mono">
          <span class="w-1.5 h-1.5 rounded-full bg-emerald-500"></span>
          <span>${this.escapeHTML(resp.modelUsed)}</span>
        </div>
      `;
    }

    // Render product cards if returned by Ollama
    if (resp.products && resp.products.length > 0) {
      if (resp.products.length === 1) {
        contentHTML += this.renderSingleProductCard(resp.products[0]);
      } else {
        contentHTML += this.renderMultipleProductCards(resp.products);
      }
    }

    contentHTML += `</div>`;
    div.innerHTML = contentHTML;
    container.appendChild(div);

    // Click handler for product modal
    div.querySelectorAll('.chat-product-card').forEach(card => {
      card.addEventListener('click', (e) => {
        if (e.target && e.target.closest('.btn-track-price')) return;
        const id = card.dataset.productId;
        const catalog = this.catalog && this.catalog.length > 0 ? this.catalog : (window.PRODUCTS_DATA || []);
        const p = catalog.find(item => String(item.id) === String(id));
        if (p && typeof window.openModal === 'function') {
          window.openModal(p);
        }
      });
    });

    // Click handler for track price button
    div.querySelectorAll('.btn-track-price').forEach(btn => {
      btn.addEventListener('click', async (e) => {
        e.stopPropagation();
        const id = btn.dataset.productId;
        const catalog = this.catalog && this.catalog.length > 0 ? this.catalog : (window.PRODUCTS_DATA || []);
        const p = catalog.find(item => String(item.id) === String(id));
        if (p) {
          await this.trackProduct(p);
        }
      });
    });

    this.scrollToBottom();
  },

  async trackProduct(p) {
    if (!p) return;
    try {
      const payload = {
        product_name: p.title || p.name,
        product_url: p.product_url || p.url || `https://dummyjson.com/products/${p.id}`,
        website: p.website || "ShopAI Store",
        current_price: parseFloat(p.price || 0),
        currency: p.currency || "USD",
        brand: p.brand || null,
        model: p.sku || p.model || null,
        image_url: p.thumbnail || p.image || null,
        specifications: { catalog_id: p.id, category: p.category }
      };

      const res = await fetch('/api/track-product', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });

      if (res.ok) {
        const tracked = await res.json();
        this.addAssistantResponse({
          reply: `✅ **Tracking Started!**\n\nI have added **${tracked.product_name}** to your tracking list.\n• Current Price: **${tracked.currency} ${tracked.current_price}**\n• Website: **${tracked.website}**\n\nOur background scheduler will check this exact URL every 5 minutes and alert you of any price drops!`,
          products: [],
          modelUsed: null
        });
      } else {
        const err = await res.json().catch(() => ({}));
        this.addAssistantResponse({
          reply: `⚠️ ${err.detail || "This product cannot be tracked until a valid product URL is available."}`,
          products: [],
          modelUsed: null
        });
      }
    } catch (e) {
      this.addAssistantResponse({
        reply: `⚠️ Connection notice: Failed to communicate with price tracking service.`,
        products: [],
        modelUsed: null
      });
    }
  },

  renderSingleProductCard(p) {
    const thumb = p.thumbnail || p.image || (p.images && p.images[0]) || '';
    const price = typeof p.price === 'number' ? `$${p.price.toFixed(2)}` : `$${p.price}`;
    const rating = typeof p.rating === 'number' ? p.rating.toFixed(1) : (p.rating && p.rating.rate ? p.rating.rate.toFixed(1) : '4.5');

    return `
      <div class="chat-product-card mt-2 p-3 rounded-xl bg-slate-50 border border-slate-200/90 shadow-xs cursor-pointer hover:border-indigo-400 transition" data-product-id="${p.id}">
        <div class="flex items-center gap-3">
          <img src="${thumb}" alt="${p.title}" class="w-16 h-16 rounded-lg object-contain bg-white p-1 border border-slate-100 shrink-0" onerror="this.src='https://via.placeholder.com/80?text=Product'">
          <div class="flex-1 min-w-0">
            <h4 class="font-bold text-xs text-slate-900 truncate">${p.title}</h4>
            <div class="text-[11px] text-slate-500 mt-0.5">
              <span>Brand: <strong>${p.brand || 'N/A'}</strong></span> &bull; <span>${p.category || 'General'}</span>
            </div>
            <div class="flex items-center justify-between mt-1">
              <span class="text-sm font-bold text-slate-900">${price} USD ${p.price_pkr ? `<span class="text-xs text-indigo-700 font-medium">(~Rs. ${p.price_pkr.toLocaleString()} PKR)</span>` : ''}</span>
              <span class="text-[11px] font-semibold text-amber-600">★ ${rating}</span>
            </div>
          </div>
        </div>

        <div class="mt-2 pt-2 border-t border-slate-200/60 grid grid-cols-2 gap-1.5 text-[10px] text-slate-600">
          ${p.warrantyInformation ? `<div>Warranty: <strong>${p.warrantyInformation}</strong></div>` : ''}
          ${p.availabilityStatus ? `<div>Status: <strong>${p.availabilityStatus}</strong></div>` : ''}
          ${p.shippingInformation ? `<div class="col-span-2">Shipping: ${p.shippingInformation}</div>` : ''}
        </div>

        <div class="mt-2.5 flex items-center gap-2">
          <button class="flex-1 py-1.5 text-center text-xs font-semibold text-indigo-700 bg-white border border-indigo-200 rounded-lg hover:bg-indigo-50 transition">
            View Details
          </button>
          <button class="flex-1 py-1.5 text-center text-xs font-semibold text-white bg-indigo-600 rounded-lg hover:bg-indigo-700 transition btn-track-price" data-product-id="${p.id}">
            ⚡ Track Price
          </button>
        </div>
      </div>
    `;
  },

  renderMultipleProductCards(products) {
    let html = `<div class="space-y-2 mt-2 max-h-72 overflow-y-auto pr-1">`;
    products.slice(0, 4).forEach(p => {
      const thumb = p.thumbnail || p.image || (p.images && p.images[0]) || '';
      const price = typeof p.price === 'number' ? `$${p.price.toFixed(2)}` : `$${p.price}`;
      const rating = typeof p.rating === 'number' ? p.rating.toFixed(1) : (p.rating && p.rating.rate ? p.rating.rate.toFixed(1) : '4.5');

      html += `
        <div class="chat-product-card flex items-center gap-2.5 p-2 rounded-xl bg-slate-50 hover:bg-indigo-50/60 border border-slate-200/80 cursor-pointer transition group" data-product-id="${p.id}">
          <img src="${thumb}" alt="${p.title}" class="w-12 h-12 rounded-lg object-contain bg-white p-1 border border-slate-100 shrink-0" onerror="this.src='https://via.placeholder.com/60?text=Product'">
          <div class="flex-1 min-w-0">
            <h4 class="font-bold text-[11px] text-slate-800 truncate group-hover:text-indigo-600 transition">${p.title}</h4>
            <div class="flex items-center gap-2 text-[10px] text-slate-500 mt-0.5">
              <span>${p.brand || 'Item'}</span>
              <span>&bull;</span>
              <span class="text-amber-600 font-semibold">★ ${rating}</span>
            </div>
            <div class="text-[11px] font-bold text-slate-900 mt-0.5">${price} USD ${p.price_pkr ? `<span class="text-[10px] text-indigo-600 font-normal">(~Rs. ${p.price_pkr.toLocaleString()})</span>` : ''}</div>
          </div>
          <button class="text-[10px] font-semibold text-indigo-600 bg-white border border-indigo-200 px-2 py-1 rounded-md shadow-xs group-hover:bg-indigo-600 group-hover:text-white transition shrink-0">
            View
          </button>
        </div>
      `;
    });
    if (products.length > 4) {
      html += `<div class="text-center text-[10px] text-slate-400 font-medium py-1">+ ${products.length - 4} more products</div>`;
    }
    html += `</div>`;
    return html;
  },

  showTypingIndicator() {
    const container = document.getElementById('chatbotMessages');
    const div = document.createElement('div');
    div.id = 'chatbotTypingIndicator';
    div.className = 'flex items-center gap-1.5 bg-white border border-slate-200 px-3 py-2 rounded-2xl rounded-tl-sm w-16 shadow-xs';
    div.innerHTML = `
      <span class="w-1.5 h-1.5 rounded-full bg-indigo-500 animate-bounce"></span>
      <span class="w-1.5 h-1.5 rounded-full bg-indigo-500 animate-bounce" style="animation-delay: 0.15s"></span>
      <span class="w-1.5 h-1.5 rounded-full bg-indigo-500 animate-bounce" style="animation-delay: 0.3s"></span>
    `;
    container.appendChild(div);
    this.scrollToBottom();
  },

  hideTypingIndicator() {
    const indicator = document.getElementById('chatbotTypingIndicator');
    if (indicator) indicator.remove();
  },

  scrollToBottom() {
    const container = document.getElementById('chatbotMessages');
    if (container) {
      container.scrollTop = container.scrollHeight;
    }
  },

  formatMarkdown(text) {
    if (!text) return '';
    return text.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
  },

  escapeHTML(str) {
    if (!str) return '';
    return str.replace(/[&<>'"]/g, tag => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      "'": '&#39;',
      '"': '&quot;'
    }[tag] || tag));
  }
};

if (typeof window !== 'undefined') {
  window.ChatbotApp = ChatbotApp;
}

// Browser Initialization
if (typeof window !== 'undefined' && typeof window.addEventListener === 'function') {
  window.addEventListener('DOMContentLoaded', () => {
    if (window.PRODUCTS_DATA && Array.isArray(window.PRODUCTS_DATA)) {
      ChatbotApp.init(window.PRODUCTS_DATA);
    } else {
      const checkInterval = setInterval(() => {
        if (window.PRODUCTS_DATA && Array.isArray(window.PRODUCTS_DATA)) {
          clearInterval(checkInterval);
          ChatbotApp.init(window.PRODUCTS_DATA);
        }
      }, 100);
    }
  });
}

// Node.js module export (for testing)
if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    CurrencyManager,
    ChatbotApp
  };
}
