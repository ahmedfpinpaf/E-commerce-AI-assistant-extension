/**
 * ShopAI Background Service Worker (Manifest V3)
 * Handles Context Menus, Notifications, Alarms, and Backend API Communication
 */

const DEFAULT_API_URL = "http://localhost:8000";

// Initialize extension defaults and Context Menu
chrome.runtime.onInstalled.addListener(() => {
  chrome.storage.local.get(["apiUrl", "notificationsEnabled"], (result) => {
    if (!result.apiUrl) {
      chrome.storage.local.set({ apiUrl: DEFAULT_API_URL });
    }
    if (result.notificationsEnabled === undefined) {
      chrome.storage.local.set({ notificationsEnabled: true });
    }
  });

  // Create context menu for quick tracking
  chrome.contextMenus.create({
    id: "shopai-track-page",
    title: "Track Price with ShopAI",
    contexts: ["page", "link"]
  });

  // Setup periodic price check alarm (every 5 mins)
  chrome.alarms.create("shopai-check-prices", {
    periodInMinutes: 5
  });
});

// Helper to get configured backend API URL
async function getApiUrl() {
  return new Promise((resolve) => {
    chrome.storage.local.get(["apiUrl"], (res) => {
      resolve(res.apiUrl || DEFAULT_API_URL);
    });
  });
}

// Track product on backend
async function trackProductOnBackend(productData) {
  const apiUrl = await getApiUrl();
  const payload = {
    product_name: productData.name,
    product_url: productData.url,
    website: productData.website || "Online Store",
    current_price: parseFloat(productData.price),
    currency: productData.currency || "PKR",
    brand: productData.brand || null,
    model: productData.model || null,
    image_url: productData.image || null,
    target_price: productData.target_price || null,
    alert_type: productData.target_price ? "target_price" : "any_drop",
    specifications: productData.specifications || null
  };

  const response = await fetch(`${apiUrl}/api/track-product`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Backend error (${response.status}): ${errorText}`);
  }

  return await response.json();
}

// Context menu click listener
chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId === "shopai-track-page" && tab?.id) {
    try {
      // Request active page product info from content script
      chrome.tabs.sendMessage(tab.id, { action: "GET_PRODUCT_INFO" }, async (response) => {
        if (chrome.runtime.lastError || !response || !response.product) {
          chrome.notifications.create({
            type: "basic",
            iconUrl: "icons/icon48.png",
            title: "ShopAI Tracker",
            message: "No product detected on this page. Please open a product detail page."
          });
          return;
        }

        const product = response.product;
        try {
          const tracked = await trackProductOnBackend(product);
          // Show chrome notification
          chrome.notifications.create({
            type: "basic",
            iconUrl: "icons/icon48.png",
            title: "ShopAI: Tracking Started!",
            message: `Now tracking ${product.name.slice(0, 40)} at ${product.currency} ${product.price.toLocaleString()}`
          });
          // Show page toast
          chrome.tabs.sendMessage(tab.id, {
            action: "SHOW_TOAST",
            message: `Tracking started for <b>${product.name.slice(0, 35)}</b> at ${product.currency} ${product.price.toLocaleString()}`,
            isSuccess: true
          });
        } catch (err) {
          chrome.notifications.create({
            type: "basic",
            iconUrl: "icons/icon48.png",
            title: "ShopAI Tracker Error",
            message: "Failed to connect to backend: " + err.message
          });
        }
      });
    } catch (e) {
      console.error("Context menu track error:", e);
    }
  }
});

// Periodic price check alarm
chrome.alarms.onAlarm.addListener(async (alarm) => {
  if (alarm.name === "shopai-check-prices") {
    try {
      const apiUrl = await getApiUrl();
      const resp = await fetch(`${apiUrl}/api/check-all-prices`, { method: "POST" });
      if (resp.ok) {
        const data = await resp.json();
        const alerts = (data.results || []).filter(r => r.alert_triggered);
        if (alerts.length > 0) {
          chrome.storage.local.get(["notificationsEnabled", "browserNotifications"], (res) => {
            const enabled = res.browserNotifications !== false && res.notificationsEnabled !== false;
            if (enabled) {
              alerts.forEach(a => {
                const curr = a.currency || "$";
                const prevFormatted = typeof a.previous_price === "number" ? a.previous_price.toLocaleString() : a.previous_price;
                const newFormatted = typeof a.new_price === "number" ? a.new_price.toLocaleString() : a.new_price;
                const dropAmt = a.drop_amount || (typeof a.previous_price === "number" && typeof a.new_price === "number" ? a.previous_price - a.new_price : 0);
                const dropPct = a.drop_percentage || (typeof a.previous_price === "number" && a.previous_price > 0 ? (dropAmt / a.previous_price * 100) : 0);
                const dropAmtStr = typeof dropAmt === "number" ? dropAmt.toLocaleString(undefined, { minimumFractionDigits: dropAmt % 1 === 0 ? 0 : 2, maximumFractionDigits: 2 }) : dropAmt;
                const dropPctStr = typeof dropPct === "number" ? dropPct.toFixed(2) : dropPct;

                chrome.notifications.create({
                  type: "basic",
                  iconUrl: "icons/icon48.png",
                  title: "Price Drop Alert",
                  message: `${a.product_name}\nPrevious: ${curr} ${prevFormatted}\nNow: ${curr} ${newFormatted}\nDropped by ${curr} ${dropAmtStr} (${dropPctStr}%)`
                });
              });
            }
          });
        }
      }

      // Check any pending notifications from scheduler
      const pendingResp = await fetch(`${apiUrl}/api/pending-notifications`);
      if (pendingResp.ok) {
        const pending = await pendingResp.json();
        if (pending && pending.length > 0) {
          chrome.storage.local.get(["notificationsEnabled", "browserNotifications"], (res) => {
            const enabled = res.browserNotifications !== false && res.notificationsEnabled !== false;
            if (enabled) {
              pending.forEach(p => {
                const curr = p.currency || "$";
                const prevFormatted = typeof p.previous_price === "number" ? p.previous_price.toLocaleString() : p.previous_price;
                const newFormatted = typeof p.current_price === "number" ? p.current_price.toLocaleString() : p.current_price;
                const dropAmt = p.drop_amount || (typeof p.previous_price === "number" && typeof p.current_price === "number" ? p.previous_price - p.current_price : 0);
                const dropPct = p.drop_percentage || (typeof p.previous_price === "number" && p.previous_price > 0 ? (dropAmt / p.previous_price * 100) : 0);
                const dropAmtStr = typeof dropAmt === "number" ? dropAmt.toLocaleString(undefined, { minimumFractionDigits: dropAmt % 1 === 0 ? 0 : 2, maximumFractionDigits: 2 }) : dropAmt;
                const dropPctStr = typeof dropPct === "number" ? dropPct.toFixed(2) : dropPct;

                chrome.notifications.create({
                  type: "basic",
                  iconUrl: "icons/icon48.png",
                  title: "Price Drop Alert",
                  message: `${p.product_name}\nPrevious: ${curr} ${prevFormatted}\nNow: ${curr} ${newFormatted}\nDropped by ${curr} ${dropAmtStr} (${dropPctStr}%)`
                });
              });
            }
          });
          await fetch(`${apiUrl}/api/ack-notifications`, { method: "POST" });
        }
      }
    } catch (err) {
      console.warn("Background alarm price check failed (server may be offline):", err);
    }
  }
});


// Message listener for popup and content script requests
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.type === "TRACK_PRODUCT") {
    trackProductOnBackend(request.product)
      .then((data) => sendResponse({ success: true, data: data }))
      .catch((err) => sendResponse({ success: false, error: err.message }));
    return true; // Keep channel open for async response
  }

  if (request.type === "CHECK_ALL_PRICES") {
    getApiUrl()
      .then((url) => fetch(`${url}/api/check-all-prices`, { method: "POST" }))
      .then((res) => res.json())
      .then((data) => sendResponse({ success: true, data: data }))
      .catch((err) => sendResponse({ success: false, error: err.message }));
    return true;
  }
});
