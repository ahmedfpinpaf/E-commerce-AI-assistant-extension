/**
 * ShopAI Content Script - Product Detection & Metadata Extractor
 * Automatically identifies e-commerce products across any store (Daraz, Amazon, OLX, eBay, Walmart, etc.)
 */

(function () {
  // Prevent duplicate injection
  if (window.__SHOPAI_CONTENT_SCRIPT_INJECTED__) return;
  window.__SHOPAI_CONTENT_SCRIPT_INJECTED__ = true;

  // Clean text helper
  function cleanText(text) {
    if (!text) return "";
    return text.replace(/\s+/g, " ").trim();
  }

  // Parse & sanitize price number from string
  function parsePrice(str) {
    if (!str) return null;
    const cleaned = str.replace(/[\u00a0\u200b\s]/g, " ").replace(/,/g, "").trim();
    const match = cleaned.match(/([0-9]+(?:\.[0-9]{1,2})?)/);
    return match ? parseFloat(match[1]) : null;
  }

  // Canonical URL cleaner: resolves link[rel="canonical"]/og:url and strips tracking/affiliate params
  function cleanCanonicalUrl(rawUrl) {
    if (!rawUrl) return window.location.href;

    let targetUrl = rawUrl;
    // Check link rel="canonical"
    const canonicalEl = document.querySelector('link[rel="canonical"]');
    if (canonicalEl && canonicalEl.href && (canonicalEl.href.startsWith("http://") || canonicalEl.href.startsWith("https://"))) {
      targetUrl = canonicalEl.href;
    } else {
      // Check og:url
      const ogUrl = document.querySelector('meta[property="og:url"]');
      if (ogUrl && ogUrl.content && (ogUrl.content.startsWith("http://") || ogUrl.content.startsWith("https://"))) {
        targetUrl = ogUrl.content;
      }
    }

    try {
      const parsed = new URL(targetUrl, window.location.href);
      const host = parsed.hostname.toLowerCase();

      // Amazon canonical normalization: /dp/ASIN
      if (host.includes("amazon.")) {
        const asinMatch = parsed.pathname.match(/\/(?:dp|gp\/product)\/([A-Z0-9]{10})/i);
        if (asinMatch) {
          return `https://${parsed.hostname}/dp/${asinMatch[1]}`;
        }
      }

      // Daraz canonical normalization: /products/...-i...-s...html
      if (host.includes("daraz.")) {
        const darazMatch = parsed.pathname.match(/(\/products\/[^?#]+)/i);
        if (darazMatch) {
          return `https://${parsed.hostname}${darazMatch[1]}`;
        }
      }

      // eBay canonical normalization: /itm/ITEMID
      if (host.includes("ebay.")) {
        const ebayMatch = parsed.pathname.match(/\/itm\/(?:[^\/]+\/)?([0-9]+)/i);
        if (ebayMatch) {
          return `https://${parsed.hostname}/itm/${ebayMatch[1]}`;
        }
      }

      // Tracking and affiliate query parameters to strip
      const trackingParams = [
        "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
        "ref", "ref_", "tag", "camp", "creative", "creativeASIN", "linkCode",
        "ascsubtag", "fbclid", "gclid", "msclkid", "spm", "scm", "pdp_npi",
        "_encoding", "pd_rd_w", "content-id", "pf_rd_p", "pf_rd_r", "pd_rd_wg",
        "pd_rd_r", "qid", "sr", "keywords", "dib", "dib_tag"
      ];

      trackingParams.forEach(param => parsed.searchParams.delete(param));
      return parsed.origin + parsed.pathname + (parsed.search ? parsed.search : "");
    } catch (e) {
      return rawUrl;
    }
  }

  // Detect currency from string or domain
  function detectCurrency(text, hostname) {
    const upper = (text || "").toUpperCase();
    if (upper.includes("PKR") || upper.includes("RS.") || upper.includes("RS ")) return "PKR";
    if (upper.includes("$") || upper.includes("USD")) return "USD";
    if (upper.includes("€") || upper.includes("EUR")) return "EUR";
    if (upper.includes("£") || upper.includes("GBP")) return "GBP";
    if (upper.includes("₹") || upper.includes("INR")) return "INR";
    if (upper.includes("AED")) return "AED";
    if (upper.includes("CAD")) return "CAD";

    // Domain heuristic
    if (hostname.endsWith(".pk")) return "PKR";
    if (hostname.endsWith(".uk")) return "GBP";
    if (hostname.endsWith(".in")) return "INR";
    return "USD";
  }

  // Detect store name from domain
  function getStoreName(hostname) {
    const host = hostname.toLowerCase();
    if (host.includes("daraz")) return "Daraz";
    if (host.includes("amazon")) return "Amazon";
    if (host.includes("olx")) return "OLX";
    if (host.includes("ebay")) return "eBay";
    if (host.includes("walmart")) return "Walmart";
    if (host.includes("aliexpress")) return "AliExpress";
    if (host.includes("bestbuy")) return "Best Buy";
    if (host.includes("target")) return "Target";
    
    // Fallback: extract domain name
    const parts = host.replace(/^www\./, "").split(".");
    if (parts.length >= 1) {
      return parts[0].charAt(0).toUpperCase() + parts[0].slice(1);
    }
    return "Online Store";
  }

  // Extract from JSON-LD
  function extractFromJsonLd() {
    const scripts = document.querySelectorAll('script[type="application/ld+json"]');
    for (const script of scripts) {
      try {
        let data = JSON.parse(script.textContent);
        if (Array.isArray(data)) {
          data = data.find(item => item["@type"] === "Product") || data[0];
        } else if (data["@graph"] && Array.isArray(data["@graph"])) {
          data = data["@graph"].find(item => item["@type"] === "Product") || data;
        }

        if (data && (data["@type"] === "Product" || data["@type"] === "IndividualProduct")) {
          const offers = Array.isArray(data.offers) ? data.offers[0] : (data.offers || {});
          let price = offers.price ? parseFloat(offers.price) : null;
          let currency = offers.priceCurrency || null;

          let image = null;
          if (typeof data.image === "string") image = data.image;
          else if (Array.isArray(data.image) && data.image.length > 0) {
            image = typeof data.image[0] === "string" ? data.image[0] : (data.image[0].url || null);
          } else if (data.image && data.image.url) {
            image = data.image.url;
          }

          let brand = null;
          if (typeof data.brand === "string") brand = data.brand;
          else if (data.brand && data.brand.name) brand = data.brand.name;

          if (data.name && price) {
            return {
              name: cleanText(data.name),
              price: price,
              currency: currency || detectCurrency(null, window.location.hostname),
              image: image,
              brand: brand,
              sku: data.sku || data.productID || null,
              description: data.description ? cleanText(data.description).slice(0, 300) : null
            };
          }
        }
      } catch (e) {
        // Continue searching
      }
    }
    return null;
  }

  // Extract from OpenGraph & Meta tags
  function extractFromMeta() {
    const getMeta = (prop) => {
      const el = document.querySelector(`meta[property="${prop}"], meta[name="${prop}"]`);
      return el ? el.getAttribute("content") : null;
    };

    const title = getMeta("og:title") || getMeta("twitter:title");
    const image = getMeta("og:image") || getMeta("twitter:image");
    const priceStr = getMeta("og:price:amount") || getMeta("product:price:amount");
    const currency = getMeta("og:price:currency") || getMeta("product:price:currency");

    if (title && priceStr) {
      const price = parsePrice(priceStr);
      if (price) {
        return {
          name: cleanText(title),
          price: price,
          currency: currency || detectCurrency(null, window.location.hostname),
          image: image,
          brand: null,
          sku: null
        };
      }
    }
    return null;
  }

  // Extract using site-specific and DOM selectors
  function extractFromDom() {
    const host = window.location.hostname.toLowerCase();
    let name = null;
    let price = null;
    let currency = null;
    let image = null;
    let brand = null;

    // 1. Daraz
    if (host.includes("daraz")) {
      const titleEl = document.querySelector(".pdp-mod-product-badge-title, .pdp-product-title, h1");
      const priceEl = document.querySelector(".pdp-price, .pdp-product-price, .price--single");
      const brandEl = document.querySelector(".pdp-product-brand__brand-link");
      const imgEl = document.querySelector(".pdp-mod-common-image, .gallery-preview-panel__image");

      if (titleEl) name = cleanText(titleEl.textContent);
      if (priceEl) {
        const raw = priceEl.textContent;
        price = parsePrice(raw);
        currency = detectCurrency(raw, host);
      }
      if (brandEl) brand = cleanText(brandEl.textContent);
      if (imgEl) image = imgEl.src;
    }

    // 2. Amazon
    else if (host.includes("amazon")) {
      const titleEl = document.querySelector("#productTitle, #title");
      const priceEl = document.querySelector(".a-price .a-offscreen, #priceblock_ourprice, #priceblock_dealprice, #corePrice_desktop .a-price .a-offscreen");
      const brandEl = document.querySelector("#bylineInfo, #brand");
      const imgEl = document.querySelector("#landingImage, #imgBlkFront, #main-image");

      if (titleEl) name = cleanText(titleEl.textContent);
      if (priceEl) {
        const raw = priceEl.textContent;
        price = parsePrice(raw);
        currency = detectCurrency(raw, host);
      }
      if (brandEl) brand = cleanText(brandEl.textContent).replace(/^Brand:\s*/i, "").replace(/^Visit the\s*/i, "").replace(/\s*Store$/i, "");
      if (imgEl) image = imgEl.getAttribute("data-old-hires") || imgEl.src;
    }

    // 3. OLX
    else if (host.includes("olx")) {
      const titleEl = document.querySelector('[data-aut-id="itemTitle"], h1');
      const priceEl = document.querySelector('[data-aut-id="itemPrice"], span._56dab877');
      const imgEl = document.querySelector('[data-aut-id="itemImage"] img, .image-gallery-slide img');

      if (titleEl) name = cleanText(titleEl.textContent);
      if (priceEl) {
        const raw = priceEl.textContent;
        price = parsePrice(raw);
        currency = detectCurrency(raw, host);
      }
      if (imgEl) image = imgEl.src;
    }

    // 4. eBay
    else if (host.includes("ebay")) {
      const titleEl = document.querySelector(".x-item-title__mainTitle, h1.x-item-title");
      const priceEl = document.querySelector(".x-price-primary span.ux-textspans, .x-bin-price__content span.ux-textspans, #prcIsum");
      const brandEl = document.querySelector(".ux-labels-values--brand .ux-textspans");
      const imgEl = document.querySelector(".ux-image-filmstrip-carousel-item img, #icImg");

      if (titleEl) name = cleanText(titleEl.textContent);
      if (priceEl) {
        const raw = priceEl.textContent;
        price = parsePrice(raw);
        currency = detectCurrency(raw, host);
      }
      if (brandEl) brand = cleanText(brandEl.textContent);
      if (imgEl) image = imgEl.src;
    }

    // 5. Generic Fallback
    if (!name || !price) {
      const h1 = document.querySelector("h1");
      if (h1 && cleanText(h1.textContent).length > 3) {
        name = cleanText(h1.textContent);
      }

      // Search for price elements with currency keywords
      const priceCandidates = Array.from(document.querySelectorAll("span, div, p, strong, b")).filter(el => {
        const txt = el.textContent || "";
        return /(?:pkr|rs\.?|\$|€|£|₹)\s*[0-9]+(?:,[0-9]+)*(?:\.[0-9]{1,2})?/i.test(txt) && txt.trim().length < 30;
      });

      if (priceCandidates.length > 0) {
        // Pick the first candidate with a prominent font size or first occurrence
        const raw = priceCandidates[0].textContent;
        price = parsePrice(raw);
        currency = detectCurrency(raw, host);
      }

      if (!image) {
        const mainImg = document.querySelector('img[data-zoom], img.product-image, img[itemprop="image"], .pdp-image img');
        if (mainImg) image = mainImg.src;
      }
    }

    if (name && price) {
      return {
        name: name,
        price: price,
        currency: currency || detectCurrency(null, host),
        image: image,
        brand: brand,
        sku: null
      };
    }
    return null;
  }

  // Master extraction pipeline
  function extractProductInfo() {
    const hostname = window.location.hostname;
    const rawUrl = window.location.href;
    const canonicalUrl = cleanCanonicalUrl(rawUrl);
    const store = getStoreName(hostname);

    // Try JSON-LD first (most structured and accurate)
    let prod = extractFromJsonLd();

    // Try Meta tags second
    if (!prod || !prod.name || !prod.price) {
      const metaProd = extractFromMeta();
      if (metaProd) {
        prod = Object.assign(metaProd, prod || {});
      }
    }

    // Try DOM selectors third
    if (!prod || !prod.name || !prod.price) {
      const domProd = extractFromDom();
      if (domProd) {
        prod = Object.assign(domProd, prod || {});
      }
    }

    if (prod && prod.name && prod.price) {
      // Clean up title (remove trailing site brands like " - Daraz.pk")
      let cleanName = prod.name;
      cleanName = cleanName.replace(/\s*[-|]\s*(Daraz|Amazon|OLX|eBay|Walmart|AliExpress).*$/i, "").trim();

      return {
        name: cleanName,
        url: canonicalUrl,
        price: prod.price,
        currency: prod.currency || detectCurrency(null, hostname),
        website: store,
        brand: prod.brand || null,
        model: prod.sku || null,
        image: prod.image || null,
        specifications: prod.description ? { summary: prod.description } : null,
        extractedAt: new Date().toISOString()
      };
    }

    return null;
  }

  // Extract individual product items if on multi-product pages (search results, category lists)
  function extractPageProducts() {
    const hostname = window.location.hostname;
    const store = getStoreName(hostname);
    const results = [];
    const seenUrls = new Set();

    const selectors = [
      '[data-qa-locator="product-item"]', '.gridItem', '.c1_t21', '.c2iY2',
      '[data-component-type="s-search-result"]', '.s-result-item[data-asin]',
      '[data-aut-id="itemBox"]', 'article',
      '.s-item', '.s-item__wrapper',
      '.product-card', '.product-item'
    ];

    const cards = document.querySelectorAll(selectors.join(", "));
    cards.forEach(card => {
      const linkEl = card.querySelector('a[href*="/products/"], a[href*="/dp/"], a[href*="/item/"], a[href*="/itm/"], a[href]');
      if (!linkEl) return;
      const rawHref = linkEl.getAttribute("href");
      if (!rawHref || rawHref.startsWith("#") || rawHref.startsWith("javascript:")) return;

      let absUrl;
      try {
        absUrl = new URL(rawHref, window.location.href).href;
      } catch (e) {
        return;
      }
      const canonicalCardUrl = cleanCanonicalUrl(absUrl);
      if (seenUrls.has(canonicalCardUrl)) return;

      let name = null;
      const titleEl = card.querySelector('h2, h3, .title, [data-qa-locator="product-title"], .s-item__title');
      if (titleEl) {
        name = cleanText(titleEl.textContent);
      } else if (linkEl.getAttribute("title")) {
        name = cleanText(linkEl.getAttribute("title"));
      } else {
        name = cleanText(linkEl.textContent);
      }
      if (!name || name.length < 3) return;

      const priceEl = card.querySelector('.price, [data-qa-locator="product-price"], .a-price .a-offscreen, .s-item__price, span._56dab877');
      let price = null;
      let currency = "PKR";
      if (priceEl) {
        price = parsePrice(priceEl.textContent);
        currency = detectCurrency(priceEl.textContent, hostname);
      } else {
        const match = card.textContent.match(/(?:pkr|rs\.?|\$|usd)?\s*([0-9]+(?:,[0-9]+)*(?:\.[0-9]+)?)/i);
        if (match) {
          price = parsePrice(match[1]);
          currency = detectCurrency(match[0], hostname);
        }
      }
      if (!price || price <= 0) return;

      const imgEl = card.querySelector("img");
      const image = imgEl ? (imgEl.src || imgEl.getAttribute("data-src")) : null;

      seenUrls.add(canonicalCardUrl);
      results.push({
        name: cleanText(name).replace(/\s*[-|]\s*(Daraz|Amazon|OLX|eBay).*$/i, ""),
        url: canonicalCardUrl,
        price: price,
        currency: currency,
        website: store,
        image: image,
        extractedAt: new Date().toISOString()
      });
    });

    return results;
  }

  // Display on-page floating toast notification
  function showToast(message, isSuccess = true) {
    let existing = document.getElementById("shopai-floating-toast");
    if (existing) existing.remove();

    const toast = document.createElement("div");
    toast.id = "shopai-floating-toast";
    toast.className = `shopai-toast ${isSuccess ? "shopai-toast-success" : "shopai-toast-info"}`;
    toast.innerHTML = `
      <div class="shopai-toast-icon">${isSuccess ? "✅" : "🔔"}</div>
      <div class="shopai-toast-body">${message}</div>
    `;

    document.body.appendChild(toast);
    setTimeout(() => {
      toast.classList.add("shopai-toast-show");
    }, 50);

    setTimeout(() => {
      toast.classList.remove("shopai-toast-show");
      setTimeout(() => toast.remove(), 400);
    }, 4000);
  }

  // Inject floating quick-track button if a product is detected
  function injectFloatingBadge(product) {
    if (!product || document.getElementById("shopai-quick-badge")) return;

    const badge = document.createElement("div");
    badge.id = "shopai-quick-badge";
    badge.className = "shopai-quick-badge";
    const currStr = `${product.currency} ${product.price.toLocaleString()}`;

    badge.innerHTML = `
      <div class="shopai-badge-content" title="Click to track price with ShopAI">
        <span class="shopai-badge-icon">⚡</span>
        <span class="shopai-badge-text">Track Price (${currStr})</span>
      </div>
      <button class="shopai-badge-close" title="Dismiss">&times;</button>
    `;

    badge.querySelector(".shopai-badge-content").addEventListener("click", () => {
      // Send tracking message to background
      chrome.runtime.sendMessage({
        type: "TRACK_PRODUCT",
        product: product
      }, (response) => {
        if (response && response.success) {
          showToast(`Tracking started for <b>${product.name.slice(0, 30)}...</b> at ${currStr}!`, true);
          badge.querySelector(".shopai-badge-text").textContent = "✓ Tracking Active";
          badge.classList.add("shopai-badge-active");
        } else {
          showToast(response?.error || "Could not connect to ShopAI backend (is server running on port 8000?)", false);
        }
      });
    });

    badge.querySelector(".shopai-badge-close").addEventListener("click", (e) => {
      e.stopPropagation();
      badge.remove();
    });

    document.body.appendChild(badge);
  }

  // Message listener from popup and background
  chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.action === "GET_PRODUCT_INFO") {
      const product = extractProductInfo();
      const pageProducts = extractPageProducts();
      const isMulti = pageProducts.length > 1 && (!product || (!window.location.href.includes("/products/") && !window.location.href.includes("/dp/") && !window.location.href.includes("/item/") && !window.location.href.includes("/itm/")));
      sendResponse({
        success: !!(product || pageProducts.length > 0),
        product: product,
        pageProducts: pageProducts,
        isMultiProductPage: isMulti
      });
      return true;
    }

    if (request.action === "SHOW_TOAST") {
      showToast(request.message, request.isSuccess !== false);
      sendResponse({ success: true });
      return true;
    }

    if (request.action === "PING") {
      sendResponse({ status: "ok" });
      return true;
    }
  });

  // Attempt initial detection after DOM idle and inject badge if on product page
  setTimeout(() => {
    const product = extractProductInfo();
    if (product) {
      injectFloatingBadge(product);
    }
  }, 1200);

})();
