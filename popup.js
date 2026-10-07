/**
 * ShopAI Chrome Extension - Popup Controller
 * Manages 3 Main Sections:
 * 1. Main Extension / Assistant (Product Assistant / Tracking + AI Chatbot)
 * 2. Monitored Products (Dashboard)
 * 3. Settings (Strictly Alert Settings & Notification Settings)
 */

document.addEventListener("DOMContentLoaded", async () => {
  // State
  let apiUrl = "http://localhost:8000";
  let activeTabProduct = null;
  let trackedProducts = [];
  let isBackendConnected = false;

  // DOM Elements
  const statusEl = document.getElementById("server-status");
  const statusText = document.getElementById("status-text");
  const navTabs = document.querySelectorAll(".nav-tab");
  const tabPanels = document.querySelectorAll(".tab-panel");
  const trackedCountBadge = document.getElementById("tracked-count-badge");
  const popupToast = document.getElementById("popup-toast");

  // Load API URL from local storage
  if (chrome.storage && chrome.storage.local) {
    const stored = await chrome.storage.local.get(["apiUrl"]);
    if (stored.apiUrl) apiUrl = stored.apiUrl;
  }

  // Toast Notification Helper
  function showToast(msg) {
    popupToast.textContent = msg;
    popupToast.classList.remove("hidden");
    popupToast.style.opacity = "1";
    setTimeout(() => {
      popupToast.style.opacity = "0";
      setTimeout(() => popupToast.classList.add("hidden"), 300);
    }, 2800);
  }

  // Currency & Number Formatter
  function formatMoney(amount, currency = "PKR") {
    if (amount === null || amount === undefined || isNaN(amount)) return `${currency} 0`;
    const num = parseFloat(amount);
    const formatted = num.toLocaleString(undefined, {
      minimumFractionDigits: num % 1 === 0 ? 0 : 2,
      maximumFractionDigits: 2
    });
    return `${currency} ${formatted}`;
  }

  // Tab Switching (assistant | tracked | settings)
  navTabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      const targetTab = tab.getAttribute("data-tab");
      navTabs.forEach(t => t.classList.remove("active"));
      tabPanels.forEach(p => p.classList.remove("active"));

      tab.classList.add("active");
      const targetPanel = document.getElementById(`panel-${targetTab}`);
      if (targetPanel) targetPanel.classList.add("active");

      if (targetTab === "tracked") {
        loadTrackedProducts();
      } else if (targetTab === "settings") {
        loadSettings();
      }
    });
  });

  // Check Backend Connectivity
  async function checkBackendConnection() {
    try {
      const res = await fetch(`${apiUrl}/api/settings`, { method: "GET" });
      if (res.ok) {
        isBackendConnected = true;
        statusEl.className = "server-status status-connected";
        statusText.textContent = "Connected";
        return true;
      }
    } catch (e) {
      // Server is offline
    }
    isBackendConnected = false;
    statusEl.className = "server-status status-offline";
    statusText.textContent = "Offline (8000)";
    return false;
  }

  // =========================================================================
  // TAB 1: MAIN EXTENSION / ASSISTANT (Product Assistant, Tracking & Chatbot)
  // =========================================================================
  const detectionLoading = document.getElementById("detection-loading");
  const productCard = document.getElementById("product-card");
  const noProductCard = document.getElementById("no-product-card");
  const productStore = document.getElementById("product-store");
  const alreadyTrackedIndicator = document.getElementById("already-tracked-indicator");
  const productImage = document.getElementById("product-image");
  const productTitle = document.getElementById("product-title");
  const productBrand = document.getElementById("product-brand");
  const productModel = document.getElementById("product-model");
  const productPrice = document.getElementById("product-price");
  const currencyPrefix = document.getElementById("currency-prefix");
  const targetPriceInput = document.getElementById("target-price-input");
  const btnTrackProduct = document.getElementById("btn-track-product");
  const btnTrackText = document.getElementById("btn-track-text");
  const btnStopTracking = document.getElementById("btn-stop-tracking");
  const manualTrackForm = document.getElementById("manual-track-form");

  // Multi-Product Selection Card Elements
  const multiProductCard = document.getElementById("multi-product-card");
  const multiProductSelect = document.getElementById("multi-product-select");
  const btnSelectProduct = document.getElementById("btn-select-product");

  // Dedicated Product Tracking Card Elements (Requirement 7)
  const dedicatedTrackingCard = document.getElementById("dedicated-tracking-card");
  const dedicatedProductName = document.getElementById("dedicated-product-name");
  const dedicatedProductImage = document.getElementById("dedicated-product-image");
  const dedicatedWebsite = document.getElementById("dedicated-website");
  const dedicatedCurrentPrice = document.getElementById("dedicated-current-price");
  const dedicatedPreviousPrice = document.getElementById("dedicated-previous-price");
  const dedicatedPriceChange = document.getElementById("dedicated-price-change");
  const dedicatedTargetRow = document.getElementById("dedicated-target-price-row");
  const dedicatedTargetPrice = document.getElementById("dedicated-target-price");
  const dedicatedStatus = document.getElementById("dedicated-status");
  const dedicatedLastChecked = document.getElementById("dedicated-last-checked");
  const dedicatedUnavailableBanner = document.getElementById("dedicated-unavailable-banner");
  const dedicatedBrandModel = document.getElementById("dedicated-brand-model");
  const btnDedicatedView = document.getElementById("btn-dedicated-view");
  const btnDedicatedStop = document.getElementById("btn-dedicated-stop");

  let detectedPageProducts = [];
  let lastAssistantProduct = null;
  let chatConversationHistory = [];

  // AI Chat Elements
  const chatContextText = document.getElementById("chat-context-text");
  const chatMessages = document.getElementById("chat-messages");
  const chatForm = document.getElementById("chat-form");
  const chatInput = document.getElementById("chat-input");
  const quickChips = document.querySelectorAll(".quick-chips .chip");

  function showDedicatedTrackingCard(p) {
    if (!p) return;
    activeTabProduct = {
      name: p.product_name,
      url: p.product_url,
      website: p.website,
      price: p.current_price,
      currency: p.currency,
      image: p.image_url,
      brand: p.brand,
      model: p.model
    };

    detectionLoading.classList.add("hidden");
    productCard.classList.add("hidden");
    noProductCard.classList.add("hidden");
    if (multiProductCard) multiProductCard.classList.add("hidden");
    dedicatedTrackingCard.classList.remove("hidden");

    dedicatedProductName.textContent = p.product_name || "Tracked Product";
    dedicatedProductImage.src = p.image_url || "icons/icon48.png";
    dedicatedWebsite.textContent = p.website || "Store";
    if (dedicatedBrandModel) {
      const bm = [p.brand, p.model].filter(x => x && x !== "N/A").join(" • ");
      if (bm) {
        dedicatedBrandModel.textContent = bm;
        dedicatedBrandModel.style.display = "inline-block";
      } else {
        dedicatedBrandModel.style.display = "none";
      }
    }
    dedicatedCurrentPrice.textContent = formatMoney(p.current_price, p.currency);

    const prevP = p.previous_price !== null && p.previous_price !== undefined ? p.previous_price : p.current_price;
    dedicatedPreviousPrice.textContent = formatMoney(prevP, p.currency);

    // Price change calculation
    if (prevP > p.current_price) {
      const drop = prevP - p.current_price;
      const pct = ((drop / prevP) * 100).toFixed(2);
      dedicatedPriceChange.innerHTML = `<span style="color:var(--success); font-weight:bold;">-${formatMoney(drop, p.currency)} (-${pct}%)</span>`;
    } else if (prevP < p.current_price) {
      const rise = p.current_price - prevP;
      dedicatedPriceChange.innerHTML = `<span style="color:var(--danger); font-weight:bold;">+${formatMoney(rise, p.currency)}</span>`;
    } else {
      dedicatedPriceChange.textContent = "None (0%)";
    }

    // Target price
    if (p.target_price) {
      dedicatedTargetRow.classList.remove("hidden");
      dedicatedTargetPrice.textContent = formatMoney(p.target_price, p.currency);
    } else {
      dedicatedTargetRow.classList.add("hidden");
    }

    // Status
    if (p.tracking_status === "unavailable") {
      dedicatedStatus.textContent = "⚠️ Unavailable";
      dedicatedStatus.className = "detail-val status-pill status-alert";
      dedicatedUnavailableBanner.classList.remove("hidden");
    } else if (p.tracking_status === "paused") {
      dedicatedStatus.textContent = "⏸️ Paused";
      dedicatedStatus.className = "detail-val status-pill status-paused";
      dedicatedUnavailableBanner.classList.add("hidden");
    } else if (p.tracking_status === "syncing") {
      dedicatedStatus.textContent = "🔄 Syncing";
      dedicatedStatus.className = "detail-val status-pill status-paused";
      dedicatedUnavailableBanner.classList.add("hidden");
    } else {
      dedicatedStatus.textContent = "🟢 Tracking";
      dedicatedStatus.className = "detail-val status-pill status-active";
      dedicatedUnavailableBanner.classList.add("hidden");
    }

    // Last checked
    if (p.last_checked) {
      const date = new Date(p.last_checked * 1000);
      dedicatedLastChecked.textContent = date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    } else {
      dedicatedLastChecked.textContent = "Just now";
    }

    // Action buttons
    btnDedicatedView.href = p.product_url;
    btnDedicatedStop.onclick = async () => {
      btnDedicatedStop.disabled = true;
      try {
        const res = await fetch(`${apiUrl}/api/tracked-products/${p.id}`, { method: "DELETE" });
        if (res.ok) {
          showToast("Stopped tracking product.");
          dedicatedTrackingCard.classList.add("hidden");
          await loadTrackedProducts();
          scanActiveTab();
        }
      } catch (e) {
        showToast("Error: " + e.message);
      } finally {
        btnDedicatedStop.disabled = false;
      }
    };

    updateChatContext({ name: p.product_name, price: p.current_price, currency: p.currency });
  }

  function showMultiProductsDetected(products) {
    detectedPageProducts = products;
    detectionLoading.classList.add("hidden");
    productCard.classList.add("hidden");
    dedicatedTrackingCard.classList.add("hidden");
    noProductCard.classList.add("hidden");
    multiProductCard.classList.remove("hidden");

    multiProductSelect.innerHTML = "";
    products.forEach((p, idx) => {
      const opt = document.createElement("option");
      opt.value = idx;
      opt.textContent = `${p.name} — ${formatMoney(p.price, p.currency)}`;
      multiProductSelect.appendChild(opt);
    });

    btnSelectProduct.onclick = () => {
      const selected = products[parseInt(multiProductSelect.value)];
      if (selected) {
        multiProductCard.classList.add("hidden");
        displayDetectedProduct(selected);
      }
    };
  }

  // Ensure content script is active in the current tab, injecting programmatically if missing
  async function ensureContentScriptActive(tabId) {
    return new Promise((resolve) => {
      chrome.tabs.sendMessage(tabId, { action: "PING" }, async (res) => {
        if (chrome.runtime.lastError || !res || res.status !== "ok") {
          try {
            if (chrome.scripting) {
              await chrome.scripting.executeScript({
                target: { tabId: tabId },
                files: ["content.js"]
              });
              await chrome.scripting.insertCSS({
                target: { tabId: tabId },
                files: ["content.css"]
              });
              setTimeout(() => resolve(true), 150);
            } else {
              resolve(false);
            }
          } catch (e) {
            resolve(false);
          }
        } else {
          resolve(true);
        }
      });
    });
  }

  async function scanActiveTab() {
    detectionLoading.classList.remove("hidden");
    productCard.classList.add("hidden");
    dedicatedTrackingCard.classList.add("hidden");
    if (multiProductCard) multiProductCard.classList.add("hidden");
    noProductCard.classList.add("hidden");

    if (!chrome.tabs) {
      showNoProductDetected();
      return;
    }

    try {
      const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
      if (!tab || !tab.id || tab.url.startsWith("chrome://")) {
        showNoProductDetected();
        return;
      }

      // Check active content script (programmatically inject if missing)
      await ensureContentScriptActive(tab.id);

      // Query extracted product info from content script
      chrome.tabs.sendMessage(tab.id, { action: "GET_PRODUCT_INFO" }, (response) => {
        if (chrome.runtime.lastError || !response) {
          showNoProductDetected();
        } else if (response.isMultiProductPage && response.pageProducts && response.pageProducts.length > 1) {
          showMultiProductsDetected(response.pageProducts);
        } else if (response.product) {
          displayDetectedProduct(response.product);
        } else if (response.pageProducts && response.pageProducts.length === 1) {
          displayDetectedProduct(response.pageProducts[0]);
        } else {
          showNoProductDetected();
        }
      });
    } catch (err) {
      showNoProductDetected();
    }
  }

  function showNoProductDetected() {
    detectionLoading.classList.add("hidden");
    productCard.classList.add("hidden");
    dedicatedTrackingCard.classList.add("hidden");
    if (multiProductCard) multiProductCard.classList.add("hidden");
    noProductCard.classList.remove("hidden");
    updateChatContext(null);
  }

  function displayDetectedProduct(product) {
    activeTabProduct = product;
    detectionLoading.classList.add("hidden");
    noProductCard.classList.add("hidden");
    if (multiProductCard) multiProductCard.classList.add("hidden");

    // Check if already tracked
    const existing = trackedProducts.find(p => p.product_url === product.url);
    if (existing) {
      showDedicatedTrackingCard(existing);
      return;
    }

    dedicatedTrackingCard.classList.add("hidden");
    productCard.classList.remove("hidden");

    productStore.textContent = product.website || "Store";
    productTitle.textContent = product.name || "Unknown Product";
    productImage.src = product.image || "icons/icon48.png";
    productPrice.textContent = formatMoney(product.price, product.currency);
    currencyPrefix.textContent = product.currency || "PKR";

    if (product.brand) {
      productBrand.textContent = product.brand;
      productBrand.style.display = "inline-block";
    } else {
      productBrand.style.display = "none";
    }

    if (product.model) {
      productModel.textContent = product.model;
      productModel.style.display = "inline-block";
    } else {
      productModel.style.display = "none";
    }

    alreadyTrackedIndicator.classList.add("hidden");
    btnTrackText.textContent = "Track This Product";
    btnStopTracking.classList.add("hidden");
    targetPriceInput.value = "";

    updateChatContext(product);
  }

  // 1-Click Track button
  btnTrackProduct.addEventListener("click", async () => {
    if (!activeTabProduct) return;
    const targetVal = parseFloat(targetPriceInput.value);

    // Visual loading state
    btnTrackProduct.disabled = true;
    btnTrackText.textContent = "⏳ Verifying & Tracking...";

    try {
      const payload = {
        product_name: activeTabProduct.name,
        product_url: activeTabProduct.url,
        website: activeTabProduct.website,
        current_price: parseFloat(activeTabProduct.price),
        currency: activeTabProduct.currency || "PKR",
        brand: activeTabProduct.brand || null,
        model: activeTabProduct.model || null,
        image_url: activeTabProduct.image || null,
        target_price: !isNaN(targetVal) ? targetVal : null,
        alert_type: !isNaN(targetVal) ? "target_price" : "any_drop",
        specifications: activeTabProduct.specifications || null
      };

      const res = await fetch(`${apiUrl}/api/track-product`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });

      if (!res.ok) {
        const errJson = await res.json().catch(() => ({}));
        throw new Error(errJson.detail || `HTTP ${res.status}`);
      }
      const tracked = await res.json();

      // Save state in extension local storage
      if (chrome.storage && chrome.storage.local) {
        await chrome.storage.local.set({
          lastTrackedProduct: tracked,
          activeTabTrackedUrl: tracked.product_url
        });
      }

      showToast(`Now tracking: ${tracked.product_name.slice(0, 30)}!`);
      await loadTrackedProducts();
      showDedicatedTrackingCard(tracked);
    } catch (err) {
      showToast("Error tracking product: " + err.message);
      btnTrackText.textContent = "Track This Product";
    } finally {
      btnTrackProduct.disabled = false;
    }
  });

  // Stop tracking button
  btnStopTracking.addEventListener("click", async () => {
    if (!activeTabProduct) return;
    const existing = trackedProducts.find(p => p.product_url === activeTabProduct.url);
    if (!existing) return;

    btnStopTracking.disabled = true;
    try {
      const res = await fetch(`${apiUrl}/api/tracked-products/${existing.id}`, { method: "DELETE" });
      if (res.ok) {
        showToast("Stopped tracking product.");
        alreadyTrackedIndicator.classList.add("hidden");
        btnTrackText.textContent = "Track This Product";
        btnStopTracking.classList.add("hidden");
        targetPriceInput.value = "";
        await loadTrackedProducts();
      }
    } catch (err) {
      showToast("Error: " + err.message);
    } finally {
      btnStopTracking.disabled = false;
    }
  });

  // Manual Tracking Form
  manualTrackForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const name = document.getElementById("manual-name").value.trim();
    const url = document.getElementById("manual-url").value.trim();
    const price = parseFloat(document.getElementById("manual-price").value);
    const currency = document.getElementById("manual-currency").value;
    const target = parseFloat(document.getElementById("manual-target").value);

    try {
      const payload = {
        product_name: name,
        product_url: url,
        website: "Custom Store",
        current_price: price,
        currency: currency,
        target_price: !isNaN(target) ? target : null,
        alert_type: !isNaN(target) ? "target_price" : "any_drop"
      };

      const res = await fetch(`${apiUrl}/api/track-product`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });

      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      showToast("Product tracked successfully!");
      manualTrackForm.reset();
      await loadTrackedProducts();
      document.querySelector('[data-tab="tracked"]').click();
    } catch (err) {
      showToast("Error: " + err.message);
    }
  });

  // Chat Context & UI
  function updateChatContext(prod) {
    if (prod && prod.name) {
      chatContextText.textContent = `Context: ${prod.name.slice(0, 32)}... (${formatMoney(prod.price, prod.currency)})`;
    } else {
      chatContextText.textContent = "Context: General browsing";
    }
  }

  function appendChatMessage(text, isUser = false) {
    const wrap = document.createElement("div");
    wrap.className = `chat-msg ${isUser ? 'chat-msg-user' : 'chat-msg-bot'}`;

    const bubble = document.createElement("div");
    bubble.className = "chat-bubble";
    let formatted = text
      .replace(/\*\*(.*?)\*\*/g, "<b>$1</b>")
      .replace(/\*(.*?)\*/g, "<i>$1</i>")
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\n/g, "<br>");
    bubble.innerHTML = formatted;

    wrap.appendChild(bubble);
    chatMessages.appendChild(wrap);
    chatMessages.scrollTop = chatMessages.scrollHeight;
  }

  function renderAssistantProductCardInChat(p) {
    if (!p) return;
    const cardWrap = document.createElement("div");
    cardWrap.className = "chat-msg chat-msg-bot";

    const title = p.name || p.title || "Recommended Product";
    const brand = p.brand || "ShopAI Catalog";
    const curr = p.currency || "USD";
    const price = typeof p.price === "number" ? p.price : parseFloat(p.price || 0);
    const pkrPrice = p.price_pkr ? ` (~PKR ${p.price_pkr.toLocaleString()})` : "";
    const imgUrl = p.image || p.image_url || p.thumbnail || (p.images && p.images[0]) || "icons/icon48.png";
    const url = p.url || p.product_url || "";

    const card = document.createElement("div");
    card.className = "chat-bubble asst-product-bubble";
    card.innerHTML = `
      <div class="asst-card-inner">
        <div class="asst-card-badge">✨ ShopAI Recommendation</div>
        <div class="asst-card-content">
          <img src="${imgUrl}" class="asst-card-thumb" onerror="this.src='icons/icon48.png'" alt="${title}">
          <div class="asst-card-info">
            <h4 class="asst-card-title">${title}</h4>
            <div class="asst-card-brand">${brand} &bull; ${p.category || 'Catalog'}</div>
            <div class="asst-card-price">${curr} ${price.toFixed(2)}${pkrPrice}</div>
          </div>
        </div>
        <div class="asst-card-actions">
          <button type="button" class="btn btn-primary btn-sm btn-track-asst-prod">⚡ Track This Product</button>
          ${url ? `<a href="${url}" target="_blank" class="btn btn-outline btn-sm">View Store Page</a>` : ""}
        </div>
      </div>
    `;

    const btnTrack = card.querySelector(".btn-track-asst-prod");
    if (btnTrack) {
      btnTrack.addEventListener("click", async () => {
        btnTrack.disabled = true;
        btnTrack.textContent = "⏳ Verifying & Tracking...";
        try {
          const payload = {
            product_id: p.id || p.productId || null,
            product_name: title,
            product_url: url,
            website: p.website || "ShopAI Store",
            current_price: price,
            currency: curr,
            brand: brand !== "ShopAI Catalog" ? brand : null,
            model: p.model || p.sku || null,
            image_url: imgUrl,
            target_price: null,
            alert_type: "any_drop",
            is_assistant_product: true,
            specifications: p.specifications || (p.description ? { summary: p.description } : null)
          };

          const res = await fetch(`${apiUrl}/api/track-product`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
          });

          if (!res.ok) {
            const errJson = await res.json().catch(() => ({}));
            throw new Error(errJson.detail || `HTTP ${res.status}`);
          }
          const tracked = await res.json();

          // Save state in extension local storage
          if (chrome.storage && chrome.storage.local) {
            await chrome.storage.local.set({
              lastTrackedProduct: tracked,
              activeTabTrackedUrl: tracked.product_url
            });
          }

          showToast(`Now tracking: ${tracked.product_name.slice(0, 30)}!`);
          await loadTrackedProducts();
          showDedicatedTrackingCard(tracked);
          btnTrack.textContent = "✓ Tracked";
          appendChatMessage(`⚡ Started tracking **${tracked.product_name}** at ${formatMoney(tracked.current_price, tracked.currency)}.`);
        } catch (err) {
          showToast(err.message);
          btnTrack.disabled = false;
          btnTrack.textContent = "⚡ Track This Product";
          appendChatMessage(`⚠️ Tracking failed: ${err.message}`);
        }
      });
    }

    cardWrap.appendChild(card);
    chatMessages.appendChild(cardWrap);
    chatMessages.scrollTop = chatMessages.scrollHeight;
  }

  // Welcome message in Assistant Chat
  appendChatMessage("👋 Hello! I am your **ShopAI Assistant**.\nAsk me about this product, tell me to *'Track this'*, or request product recommendations.");

  chatForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const query = chatInput.value.trim();
    if (!query) return;

    chatInput.value = "";
    appendChatMessage(query, true);
    chatConversationHistory.push({ role: "user", content: query });

    const typingWrap = document.createElement("div");
    typingWrap.className = "chat-msg chat-msg-bot";
    typingWrap.innerHTML = `<div class="chat-bubble"><i>Thinking...</i></div>`;
    chatMessages.appendChild(typingWrap);
    chatMessages.scrollTop = chatMessages.scrollHeight;

    try {
      // Send chat request with active webpage product and last assistant product
      const res = await fetch(`${apiUrl}/api/extension/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: query,
          active_product: activeTabProduct,
          page_products: detectedPageProducts,
          last_assistant_product: lastAssistantProduct,
          history: chatConversationHistory.slice(-8)
        })
      });

      typingWrap.remove();

      if (res.ok) {
        const data = await res.json();
        if (data.reply) {
          appendChatMessage(data.reply);
          chatConversationHistory.push({ role: "assistant", content: data.reply });
        }

        // If assistant returned a recommended product from catalog
        if (data.assistant_product || (data.products && data.products.length > 0)) {
          const asstProd = data.assistant_product || data.products[0];
          lastAssistantProduct = asstProd;
          renderAssistantProductCardInChat(asstProd);
          updateChatContext({
            name: asstProd.title || asstProd.name,
            price: asstProd.price,
            currency: asstProd.currency || "USD"
          });
        }

        // If a product tracking record was created
        if (data.tracked_product_added) {
          await loadTrackedProducts();
          if (data.product) {
            showDedicatedTrackingCard(data.product);
            showToast(`Now tracking: ${(data.product.product_name || "product").slice(0, 30)}!`);
          } else {
            scanActiveTab();
          }
        }
      } else {
        // Fallback to integrated Ollama LLM chat endpoint
        const chatRes = await fetch(`${apiUrl}/api/chat`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message: query, history: chatConversationHistory.slice(-8) })
        });
        if (chatRes.ok) {
          const chatData = await chatRes.json();
          appendChatMessage(chatData.reply || "How can I assist you?");
          chatConversationHistory.push({ role: "assistant", content: chatData.reply || "" });
          if (chatData.products && chatData.products.length > 0) {
            lastAssistantProduct = chatData.products[0];
            renderAssistantProductCardInChat(chatData.products[0]);
          }
        } else {
          appendChatMessage("⚠️ Assistant offline. Please ensure backend server is running.");
        }
      }
    } catch (err) {
      typingWrap.remove();
      appendChatMessage("⚠️ Connection error: Please ensure ShopAI backend is running on `http://localhost:8000`.");
    }
  });

  // Quick Chips
  quickChips.forEach(chip => {
    chip.addEventListener("click", () => {
      chatInput.value = chip.getAttribute("data-msg");
      chatForm.dispatchEvent(new Event("submit"));
    });
  });

  // =========================================================================
  // TAB 2: TRACKED PRODUCTS (Products Being Monitored)
  // =========================================================================
  const trackedItemsList = document.getElementById("tracked-items-list");
  const trackedEmptyState = document.getElementById("tracked-empty-state");
  const trackedSearchInput = document.getElementById("tracked-search-input");
  const btnRefreshAll = document.getElementById("btn-refresh-all");

  async function loadTrackedProducts() {
    try {
      const res = await fetch(`${apiUrl}/api/tracked-products`);
      if (res.ok) {
        trackedProducts = await res.json();
        trackedCountBadge.textContent = trackedProducts.length;
        renderTrackedProducts(trackedProducts);
      }
    } catch (err) {
      console.warn("Could not load tracked products:", err);
    }
  }

  function renderTrackedProducts(items) {
    trackedItemsList.innerHTML = "";
    const filter = trackedSearchInput.value.toLowerCase().trim();
    const filtered = items.filter(p =>
      p.product_name.toLowerCase().includes(filter) ||
      (p.website && p.website.toLowerCase().includes(filter))
    );

    if (filtered.length === 0) {
      trackedEmptyState.classList.remove("hidden");
      return;
    }
    trackedEmptyState.classList.add("hidden");

    filtered.forEach((p) => {
      const card = document.createElement("div");
      card.className = "tracked-item-card";

      // Price Drop calculation
      let priceChangeBadge = "";
      if (p.previous_price && p.previous_price > p.current_price) {
        const drop = p.previous_price - p.current_price;
        const pct = ((drop / p.previous_price) * 100).toFixed(0);
        priceChangeBadge = `<span class="price-change-badge drop">-$${drop.toLocaleString()} (-${pct}%)</span>`;
      } else if (p.previous_price && p.previous_price < p.current_price) {
        const rise = p.current_price - p.previous_price;
        priceChangeBadge = `<span class="price-change-badge rise">+$${rise.toLocaleString()}</span>`;
      }

      // Status pill
      const statusClass = p.tracking_status === "active" ? "status-active" : (p.tracking_status === "paused" ? "status-paused" : "status-alert");
      const statusLabel = p.tracking_status || "active";

      card.innerHTML = `
        <div class="tracked-item-top">
          <img class="item-thumb" src="${p.image_url || 'icons/icon48.png'}" alt="Thumb" onerror="this.src='icons/icon48.png'">
          <div class="item-info">
            <a href="${p.product_url}" target="_blank" class="item-title-link" title="${p.product_name}">${p.product_name}</a>
            <div class="item-sub-meta">
              <span class="store-badge">${p.website || 'Store'}</span>
              ${p.target_price ? `<span class="tag">🎯 Alert &lt; ${formatMoney(p.target_price, p.currency)}</span>` : ''}
              <span class="tag">🕒 ${p.last_checked ? new Date(p.last_checked * 1000).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'}) : 'Checked'}</span>
            </div>
          </div>
        </div>

        <div class="item-price-row">
          <div class="item-prices">
            <span class="item-curr-price">${formatMoney(p.current_price, p.currency)}</span>
            ${p.previous_price ? `<span class="item-prev-price">${formatMoney(p.previous_price, p.currency)}</span>` : ''}
          </div>
          ${priceChangeBadge}
        </div>

        ${p.tracking_status === "unavailable" ? `<div class="unavailable-banner">⚠️ The tracked product is currently unavailable or could not be found.</div>` : ''}

        <div class="item-actions-row">
          <span class="item-status-pill ${statusClass}">${statusLabel === 'active' ? '🟢 Tracking' : (statusLabel === 'unavailable' ? '⚠️ Unavailable' : statusLabel)}</span>
          <div class="item-action-btns">
            <button class="btn-icon-only btn-check-price" data-id="${p.id}" title="Check Price Now">🔄</button>
            <button class="btn-icon-only btn-toggle-history" data-id="${p.id}" title="Price History">📈</button>
            <button class="btn-icon-only btn-toggle-pause" data-id="${p.id}" data-status="${p.tracking_status}" title="${p.tracking_status === 'paused' ? 'Resume' : 'Pause'}">${p.tracking_status === 'paused' ? '▶️' : '⏸️'}</button>
            <button class="btn-icon-only btn-delete-item" data-id="${p.id}" title="Untrack">🗑️</button>
          </div>
        </div>

        <div class="history-container hidden" id="history-${p.id}">
          <div class="history-loading">Loading price history...</div>
        </div>
      `;

      // Actions
      card.querySelector(".btn-check-price").addEventListener("click", async () => {
        showToast("Checking live price...");
        try {
          const res = await fetch(`${apiUrl}/api/check-price/${p.id}`, { method: "POST" });
          if (res.ok) {
            const data = await res.json();
            if (data.alert_triggered) {
              showToast(`🚨 Price dropped to ${formatMoney(data.new_price, p.currency)}! Alert sent.`);
            } else {
              showToast(`Price: ${formatMoney(data.new_price || p.current_price, p.currency)}`);
            }
            await loadTrackedProducts();
          }
        } catch (e) {
          showToast("Failed to check price.");
        }
      });

      card.querySelector(".btn-toggle-pause").addEventListener("click", async () => {
        const newStatus = p.tracking_status === "paused" ? "active" : "paused";
        try {
          const res = await fetch(`${apiUrl}/api/tracked-products/${p.id}`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ tracking_status: newStatus })
          });
          if (res.ok) {
            showToast(`Tracking ${newStatus}.`);
            await loadTrackedProducts();
          }
        } catch (e) {
          showToast("Error updating status.");
        }
      });

      card.querySelector(".btn-delete-item").addEventListener("click", async () => {
        if (!confirm(`Stop tracking "${p.product_name}"?`)) return;
        try {
          const res = await fetch(`${apiUrl}/api/tracked-products/${p.id}`, { method: "DELETE" });
          if (res.ok) {
            showToast("Item removed.");
            await loadTrackedProducts();
            scanActiveTab();
          }
        } catch (e) {
          showToast("Error deleting item.");
        }
      });

      card.querySelector(".btn-toggle-history").addEventListener("click", async () => {
        const histContainer = card.querySelector(`#history-${p.id}`);
        if (!histContainer.classList.contains("hidden")) {
          histContainer.classList.add("hidden");
          return;
        }
        histContainer.classList.remove("hidden");
        try {
          const res = await fetch(`${apiUrl}/api/tracked-products/${p.id}/history`);
          if (res.ok) {
            const histData = await res.json();
            if (histData.length === 0) {
              histContainer.innerHTML = "<div>No price changes recorded yet.</div>";
            } else {
              histContainer.innerHTML = histData.map(h => `
                <div class="history-entry">
                  <span>${new Date(h.checked_at).toLocaleDateString()} ${new Date(h.checked_at).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})}</span>
                  <b>${formatMoney(h.price, h.currency || p.currency)}</b>
                </div>
              `).join("");
            }
          }
        } catch (e) {
          histContainer.innerHTML = "<div>Failed to load history.</div>";
        }
      });

      trackedItemsList.appendChild(card);
    });
  }

  trackedSearchInput.addEventListener("input", () => {
    renderTrackedProducts(trackedProducts);
  });

  btnRefreshAll.addEventListener("click", async () => {
    showToast("Checking all monitored prices...");
    try {
      const res = await fetch(`${apiUrl}/api/check-all-prices`, { method: "POST" });
      if (res.ok) {
        showToast("Price check complete!");
        await loadTrackedProducts();
      }
    } catch (e) {
      showToast("Error checking prices.");
    }
  });

  // =========================================================================
  // TAB 3: SETTINGS (CLEAN & FOCUSED ONLY ON ALERT AND NOTIFICATION SETTINGS)
  // =========================================================================
  const settingsForm = document.getElementById("settings-form");
  const settingPriceDropAlerts = document.getElementById("setting-price-drop-alerts");
  const settingTrackedAlertsEnabled = document.getElementById("setting-tracked-alerts-enabled");
  const settingMinDropPct = document.getElementById("setting-min-drop-pct");
  const settingMinDropAmount = document.getElementById("setting-min-drop-amount");
  const settingAlertFrequency = document.getElementById("setting-alert-frequency");

  const settingBrowserNotifications = document.getElementById("setting-browser-notifications");
  const settingEmailNotifications = document.getElementById("setting-email-notifications");
  const settingAlertEmail = document.getElementById("setting-alert-email");
  const settingEmailPref = document.getElementById("setting-email-pref");
  const settingApiUrl = document.getElementById("setting-api-url");
  const btnSendTestEmail = document.getElementById("btn-send-test-email");
  const testEmailStatus = document.getElementById("test-email-status");

  async function loadSettings() {
    try {
      const res = await fetch(`${apiUrl}/api/settings`);
      if (res.ok) {
        const data = await res.json();
        // 1. Alert Settings
        if (data.price_drop_alerts_enabled !== undefined) {
          settingPriceDropAlerts.checked = data.price_drop_alerts_enabled === "true";
        }
        if (data.tracked_alerts_enabled !== undefined) {
          settingTrackedAlertsEnabled.checked = data.tracked_alerts_enabled === "true";
        }
        if (data.price_drop_pct_threshold) {
          settingMinDropPct.value = data.price_drop_pct_threshold;
        }
        if (data.min_price_drop_amount) {
          settingMinDropAmount.value = data.min_price_drop_amount;
        }
        if (data.alert_frequency) {
          settingAlertFrequency.value = data.alert_frequency;
        }

        // 2. Notification Settings
        if (data.browser_notifications_enabled !== undefined) {
          settingBrowserNotifications.checked = data.browser_notifications_enabled === "true";
        }
        if (data.email_notifications_enabled !== undefined) {
          settingEmailNotifications.checked = data.email_notifications_enabled === "true";
        }
        if (data.alert_email) {
          settingAlertEmail.value = data.alert_email;
        }
        if (data.email_alert_preferences) {
          settingEmailPref.value = data.email_alert_preferences;
        }
      }
    } catch (e) {
      console.warn("Could not load backend settings:", e);
    }

    if (chrome.storage && chrome.storage.local) {
      const stored = await chrome.storage.local.get([
        "apiUrl",
        "alertEmail",
        "priceDropAlerts",
        "trackedAlerts",
        "minDropPct",
        "minDropAmount",
        "alertFrequency",
        "browserNotifications",
        "emailNotifications",
        "emailPref"
      ]);
      if (stored.apiUrl) settingApiUrl.value = stored.apiUrl;
      if (stored.alertEmail && !settingAlertEmail.value) settingAlertEmail.value = stored.alertEmail;
      if (stored.priceDropAlerts !== undefined) settingPriceDropAlerts.checked = stored.priceDropAlerts;
      if (stored.trackedAlerts !== undefined) settingTrackedAlertsEnabled.checked = stored.trackedAlerts;
      if (stored.minDropPct) settingMinDropPct.value = stored.minDropPct;
      if (stored.minDropAmount) settingMinDropAmount.value = stored.minDropAmount;
      if (stored.alertFrequency) settingAlertFrequency.value = stored.alertFrequency;
      if (stored.browserNotifications !== undefined) settingBrowserNotifications.checked = stored.browserNotifications;
      if (stored.emailNotifications !== undefined) settingEmailNotifications.checked = stored.emailNotifications;
      if (stored.emailPref) settingEmailPref.value = stored.emailPref;
    }
  }

  settingsForm.addEventListener("submit", async (e) => {
    e.preventDefault();

    const priceDropAlerts = settingPriceDropAlerts.checked ? "true" : "false";
    const trackedAlerts = settingTrackedAlertsEnabled.checked ? "true" : "false";
    const minDropPct = settingMinDropPct.value;
    const minDropAmount = settingMinDropAmount.value.trim();
    const alertFrequency = settingAlertFrequency.value;

    const browserNotifications = settingBrowserNotifications.checked ? "true" : "false";
    const emailNotifications = settingEmailNotifications.checked ? "true" : "false";
    const email = settingAlertEmail.value.trim();
    const emailPref = settingEmailPref.value;
    const newApiUrl = settingApiUrl.value.trim() || "http://localhost:8000";

    const payload = {
      price_drop_alerts_enabled: priceDropAlerts,
      tracked_alerts_enabled: trackedAlerts,
      price_drop_pct_threshold: minDropPct,
      min_price_drop_amount: minDropAmount || "0",
      alert_frequency: alertFrequency,
      browser_notifications_enabled: browserNotifications,
      email_notifications_enabled: emailNotifications,
      alert_email: email,
      email_alert_preferences: emailPref
    };

    try {
      // Save to backend
      const res = await fetch(`${newApiUrl}/api/settings`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });

      // Save to chrome storage
      if (chrome.storage && chrome.storage.local) {
        await chrome.storage.local.set({
          apiUrl: newApiUrl,
          alertEmail: email,
          priceDropAlerts: settingPriceDropAlerts.checked,
          trackedAlerts: settingTrackedAlertsEnabled.checked,
          minDropPct: minDropPct,
          minDropAmount: minDropAmount,
          alertFrequency: alertFrequency,
          browserNotifications: settingBrowserNotifications.checked,
          emailNotifications: settingEmailNotifications.checked,
          emailPref: emailPref
        });
      }

      apiUrl = newApiUrl;
      showToast("Settings saved successfully!");
      checkBackendConnection();
    } catch (err) {
      showToast("Error saving settings: " + err.message);
    }
  });

  // Test Email Button
  btnSendTestEmail.addEventListener("click", async () => {
    btnSendTestEmail.disabled = true;
    testEmailStatus.className = "status-box hidden";
    showToast("Sending test price-drop alert email...");

    try {
      const res = await fetch(`${apiUrl}/api/test-email-alert`, { method: "POST" });
      const data = await res.json();
      if (res.ok && data.success) {
        testEmailStatus.className = "status-box success";
        testEmailStatus.textContent = `✅ Test alert dispatched to ${data.recipient || settingAlertEmail.value || 'configured email'}!`;
        testEmailStatus.classList.remove("hidden");
      } else {
        testEmailStatus.className = "status-box error";
        testEmailStatus.textContent = `❌ Email failed: ${data.message || 'Check SMTP in .env'}`;
        testEmailStatus.classList.remove("hidden");
      }
    } catch (err) {
      testEmailStatus.className = "status-box error";
      testEmailStatus.textContent = "❌ Connection failed: " + err.message;
      testEmailStatus.classList.remove("hidden");
    } finally {
      btnSendTestEmail.disabled = false;
    }
  });

  // Initialization
  await checkBackendConnection();
  await loadTrackedProducts();
  await scanActiveTab();
});
