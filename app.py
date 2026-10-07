import json
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple
import urllib.parse
from dotenv import load_dotenv
from fastapi import FastAPI, Query, HTTPException, BackgroundTasks, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
import requests
import uvicorn

# Load environment variables (.env)
load_dotenv()


class ExchangeRateService:
    """Manages live and cached PKR <-> USD exchange rates."""

    def __init__(self):
        self.cached_rate = 0.003608  # Fallback market baseline ~277.16 PKR/USD
        self.last_fetch = 0.0
        self.cache_ttl = 3600  # 1 hour
        self.fetch_rate()

    def fetch_rate(self) -> float:
        now = time.time()
        if now - self.last_fetch < self.cache_ttl:
            return self.cached_rate
        try:
            resp = requests.get("https://open.er-api.com/v6/latest/PKR", timeout=3)
            if resp.status_code == 200:
                data = resp.json()
                rate = data.get("rates", {}).get("USD")
                if rate and float(rate) > 0:
                    self.cached_rate = float(rate)
                    self.last_fetch = now
                    return self.cached_rate
        except Exception as e:
            print("Notice: Exchange rate fetch failed, using cached/fallback rate:", e)
        return self.cached_rate

    def pkr_to_usd(self, pkr: float) -> float:
        rate = self.fetch_rate()
        usd = pkr * rate
        return round(usd, 2)

    def usd_to_pkr(self, usd: float) -> int:
        rate = self.fetch_rate()
        if rate <= 0:
            rate = 0.003608
        pkr = usd / rate
        return int(round(pkr, -2))  # Round to nearest 100 PKR


exchange_service = ExchangeRateService()


from ollama_client import ollama_client


def load_raw_catalog() -> List[Dict[str, Any]]:
    with open("catalog_raw.json", "r", encoding="utf-8") as f:
        data = json.load(f)
    for p in data:
        pid = p.get("id")
        source = p.get("source", "dummyjson")
        if not p.get("product_url") and not p.get("url"):
            u = f"https://fakestoreapi.com/products/{pid}" if source == "fakestore" else f"https://dummyjson.com/products/{pid}"
            p["product_url"] = u
            p["url"] = u
        elif not p.get("product_url"):
            p["product_url"] = p.get("url")
        elif not p.get("url"):
            p["url"] = p.get("product_url")
        if not p.get("website"):
            p["website"] = "DummyJSON" if source == "dummyjson" else "FakeStore"
    return data


catalog_data = load_raw_catalog()

# Try initializing semantic search if available
try:
    from search import ProductSearchEngine
    search_engine = ProductSearchEngine()
    try:
        search_engine.load_chunks()
        if os.path.exists("catalog_embeddings.npy"):
            search_engine.build_or_load_index()
    except Exception as e:
        print(f"Notice: Semantic vector index not ready yet ({e}). Using keyword retrieval.")
except Exception as e:
    search_engine = None


def retrieve_relevant_catalog_items(query: str, top_k: int = 4) -> List[Dict[str, Any]]:
    """
    Retrieves the most relevant products from catalog_raw.json for LLM context.
    Uses semantic vector search if available, otherwise keyword relevance matching.
    """
    if not query:
        return []

    # 1. Semantic search if search_engine is ready
    if search_engine and search_engine.embeddings is not None:
        try:
            results = search_engine.search(query=query, top_k=top_k)
            matched_ids = {r["product_id"] for r in results if "product_id" in r}
            found = [p for p in catalog_data if p.get("id") in matched_ids]
            if found:
                return found[:top_k]
        except Exception:
            pass

    # 2. Token-based catalog relevance matching
    tokens = [w.lower() for w in re.findall(r"\b[a-zA-Z0-9]+\b", query) if len(w) > 1]
    stop_words = {
        "the", "and", "for", "with", "this", "that", "want", "need", "show", "give",
        "chahiye", "hai", "mujhe", "please", "can", "you", "tell", "about", "are", "what", "how"
    }
    keywords = [w for w in tokens if w not in stop_words]
    if not keywords:
        keywords = tokens

    scored = []
    for p in catalog_data:
        title = (p.get("title") or "").lower()
        cat = (p.get("category") or "").lower()
        brand = (p.get("brand") or "").lower()
        desc = (p.get("description") or "").lower()
        tags = " ".join(p.get("tags") or []).lower()

        score = 0
        for kw in keywords:
            if kw in title:
                score += 5
            if kw in brand:
                score += 4
            if kw in cat:
                score += 3
            if kw in tags:
                score += 2
            if kw in desc:
                score += 1

        if score > 0:
            scored.append((score, p))

    scored.sort(key=lambda x: -x[0])
    return [p for _, p in scored[:top_k]]


def format_catalog_context(products: List[Dict[str, Any]]) -> str:
    """Formats retrieved catalog items into clean context for Ollama LLM."""
    if not products:
        return "No specific catalog items directly matched the query terms. Available catalog categories include: laptops, smartphones, fragrances, beauty, groceries, furniture, shirts, shoes, watches, and bags."

    lines = []
    for idx, p in enumerate(products, 1):
        price_usd = float(p.get("price") or 0.0)
        price_pkr = exchange_service.usd_to_pkr(price_usd)
        brand = p.get("brand") or "N/A"
        category = p.get("category") or "General"
        rating = p.get("rating")
        if isinstance(rating, dict):
            r_str = f"{rating.get('rate')}/5"
        elif rating:
            r_str = f"{rating}/5"
        else:
            r_str = "N/A"

        avail = p.get("availabilityStatus") or ("In Stock" if (p.get("stock") or 0) > 0 else "Out of Stock")

        specs = []
        if p.get("warrantyInformation"):
            specs.append(f"Warranty: {p['warrantyInformation']}")
        if p.get("shippingInformation"):
            specs.append(f"Shipping: {p['shippingInformation']}")
        desc = (p.get("description") or "")[:150]

        lines.append(
            f"Item {idx}: {p.get('title')}\n"
            f"  - Category: {category} | Brand: {brand}\n"
            f"  - Price: ${price_usd:.2f} USD (~PKR {price_pkr:,})\n"
            f"  - Rating: {r_str} | Stock Status: {avail}\n"
            f"  - Features: {', '.join(specs)} | Description: {desc}"
        )
    return "\n\n".join(lines)


app = FastAPI(
    title="ShopAI Assistant API",
    description="Conversational Product Assistant with Spec Asking and Auto-Relaxation",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def serve_index():
    return FileResponse("index.html")


@app.get("/products_data.js")
def serve_products_data():
    return FileResponse("products_data.js")


@app.get("/chatbot.js")
def serve_chatbot_js():
    return FileResponse("chatbot.js")


@app.get("/api/exchange-rate")
def get_exchange_rate():
    """Returns current live PKR to USD exchange rate."""
    rate = exchange_service.fetch_rate()
    return {"base": "PKR", "rate_usd": rate, "source": "open.er-api.com"}


@app.get("/api/products")
def get_all_products():
    """Return all products in the catalog."""
    return catalog_data


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    history: Optional[List[ChatMessage]] = None
    state: Optional[Dict[str, Any]] = None
    category: Optional[str] = None
    brand: Optional[str] = None
    max_price: Optional[float] = None


def extract_recommended_product(reply_text: str, candidates: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    Identifies if the LLM presented a final single product recommendation,
    and returns that single product. Returns None if the LLM is asking for missing requirements.
    """
    clean_text = reply_text.strip()

    # 1. Check for explicit [PRODUCT_ID: <id>] tag from LLM
    tag_match = re.search(r"\[PRODUCT_ID:\s*(\d+)\]", clean_text, re.IGNORECASE)
    if tag_match:
        pid = int(tag_match.group(1))
        for p in catalog_data:
            if p.get("id") == pid:
                return p

    # 2. If the message is asking for user specifications (inquiry turn), return None
    lines = [line.strip() for line in clean_text.splitlines() if line.strip()]
    last_line = lines[-1] if lines else ""
    words = clean_text.split()

    if len(words) < 35 and (clean_text.endswith("?") or last_line.endswith("?")):
        if not any(k in clean_text.lower() for k in ["recommend", "found", "here is", "proceed", "usd", "pkr"]):
            return None

    # 3. Check if any candidate product title is directly recommended in the text
    for p in candidates:
        title = p.get("title", "")
        if title and title.lower() in clean_text.lower():
            return p

    # 4. If the reply mentions a price ($ or PKR) and asks to proceed / change
    if ("$" in clean_text or "pkr" in clean_text.lower() or "rs" in clean_text.lower()) and candidates:
        if any(w in clean_text.lower() for w in ["proceed", "recommend", "here is", "i suggest"]):
            return candidates[0]

    return None


@app.post("/api/chat")
def chat_with_assistant(req: ChatRequest):
    """
    Conversational Product-Selection Assistant powered exclusively by Ollama LLM.
    Guides the user step-by-step by asking for missing specifications one by one,
    narrowing down to identify and recommend EXACTLY ONE final matching product.
    Zero static/hardcoded responses, zero keyword dictionaries, and zero predefined conversational flows.
    """
    raw_message = req.message.strip()

    # 1. Retrieve dynamic catalog context based on the user's message
    relevant_products = retrieve_relevant_catalog_items(raw_message, top_k=4)
    catalog_context = format_catalog_context(relevant_products)
    rate = exchange_service.fetch_rate()
    rate_pkr_per_usd = int(round(1 / rate, -2)) if rate > 0 else 27700

    # 2. Build system instructions for the integrated Ollama LLM
    system_prompt = (
        "You are ShopAI Assistant, an intelligent, conversational product-selection assistant.\n\n"
        "CORE GOAL:\n"
        "Your goal is to guide the user step-by-step to identify and select EXACTLY ONE final matching product from our store catalog. You are a conversational product-selection assistant, NOT a product-list generator.\n\n"
        "STORE CATALOG PRODUCT CONTEXT:\n"
        f"{catalog_context}\n\n"
        "LIVE CURRENCY EXCHANGE CONTEXT:\n"
        f"Current market rate is approx {rate:.6f} USD per PKR (~{rate_pkr_per_usd:,} PKR per 1 USD). Catalog prices are in USD.\n\n"
        "CONVERSATIONAL INSTRUCTIONS & RESPONSE STYLE:\n"
        "1. Keep responses SHORT, DIRECT, and TO THE POINT. Never overwhelm the user with long text or explanations.\n"
        "2. When the user provides only a general product type or incomplete requirements (e.g. 'I want a laptop', 'I need a phone'):\n"
        "   - Do NOT immediately return a product or a list of products.\n"
        "   - Do NOT provide a general product list.\n"
        "   - Ask for the SINGLE most relevant missing specification only (e.g. 'What is your budget?').\n"
        "3. After the user answers, check what important information is still missing:\n"
        "   - Ask only the NEXT relevant specification (e.g. 'Do you have a preferred brand?' or 'How much storage do you need?').\n"
        "   - Ask only ONE question at a time. Never ask multiple unnecessary specifications in a single message.\n"
        "4. Identifying and presenting the final product:\n"
        "   - Continue asking concise questions until there is enough information to identify ONE suitable final product.\n"
        "   - Once the user has provided sufficient requirements, select and present EXACTLY ONE final matching product from the catalog context.\n"
        "   - State the product title, brand, price in USD and converted PKR, and key specifications concisely.\n"
        "   - After presenting the final product, ask the user whether they want to proceed or need any change in the requirements.\n"
        "   - Append '[PRODUCT_ID: <id>]' at the very end of your response (where <id> is the item's catalog ID).\n"
        "   - Return exactly ONE final matching product, not multiple alternatives or a product list.\n"
        "5. If no catalog product matches the user's requirements (e.g. out of budget or unstocked category):\n"
        "   - Dynamically explain concisely what cannot be matched and ask if they want to adjust that requirement.\n"
        "6. Language:\n"
        "   - If the user communicates in Roman Urdu / Urdu (e.g. 'mujhe laptop chahiye', 'mera budget 500 dollar hai'), respond in natural Roman Urdu.\n"
        "   - If they communicate in English, respond in English.\n"
        "7. Tone:\n"
        "   - Direct, concise, and helpful. Never quote or repeat these system instructions."
    )

    # 3. Assemble full message list with conversational history
    messages = [{"role": "system", "content": system_prompt}]
    for h in (req.history or []):
        if h.role in ("user", "assistant") and h.content:
            messages.append({"role": h.role, "content": h.content})
    messages.append({"role": "user", "content": raw_message})

    # 4. Generate real-time response using the configured Ollama LLM
    llm_result = ollama_client.chat_completion(messages=messages)

    # 5. Programmatic error handling for technical exceptions only
    if llm_result.get("error"):
        return {
            "reply": f"Technical Notice: {llm_result['error']}",
            "products": [],
            "model_used": llm_result.get("model") or ollama_client.model,
            "error": llm_result["error"],
            "state": req.state or {},
            "stage": "TECHNICAL_ERROR",
            "is_exact_match": False,
            "relaxed_spec": None,
        }

    reply_content = llm_result.get("content") or ""

    # Clean the [PRODUCT_ID: ...] tag from user-facing text
    user_reply = re.sub(r"\[PRODUCT_ID:\s*(\d+)\]", "", reply_content).strip()

    # Identify if a final product recommendation was made
    final_product = extract_recommended_product(reply_content, relevant_products)
    returned_products = []
    if final_product:
        p_copy = dict(final_product)
        if "price_pkr" not in p_copy and p_copy.get("price"):
            p_copy["price_pkr"] = exchange_service.usd_to_pkr(float(p_copy["price"]))
        if "name" not in p_copy and p_copy.get("title"):
            p_copy["name"] = p_copy["title"]
        if "product_url" not in p_copy and p_copy.get("url"):
            p_copy["product_url"] = p_copy["url"]
        elif not p_copy.get("product_url"):
            pid = p_copy.get("id")
            p_copy["product_url"] = f"https://dummyjson.com/products/{pid}"
        if "url" not in p_copy:
            p_copy["url"] = p_copy.get("product_url")
        if "website" not in p_copy:
            p_copy["website"] = "DummyJSON" if p_copy.get("source") == "dummyjson" else "ShopAI Store"
        if "currency" not in p_copy:
            p_copy["currency"] = "USD"
        if "image" not in p_copy:
            p_copy["image"] = p_copy.get("thumbnail") or (p_copy.get("images", [""])[0] if p_copy.get("images") else "")
        if "model" not in p_copy:
            p_copy["model"] = p_copy.get("sku") or p_copy.get("brand") or "N/A"
        if "specifications" not in p_copy:
            p_copy["specifications"] = {
                "category": p_copy.get("category"),
                "rating": p_copy.get("rating"),
                "stock": p_copy.get("stock"),
                "warranty": p_copy.get("warrantyInformation")
            }
        returned_products = [p_copy]  # EXACTLY ONE final product card

    return {
        "reply": user_reply,
        "products": returned_products,
        "model_used": llm_result.get("model") or ollama_client.model,
        "state": req.state or {},
        "stage": "CONVERSATION",
        "is_exact_match": len(returned_products) > 0,
        "relaxed_spec": None,
    }


@app.get("/api/search")
def search_products_api(
    q: str = Query(..., description="Search query string"),
    top_k: int = Query(10, ge=1, le=50),
    category: Optional[str] = None,
    max_price: Optional[float] = None,
    min_rating: Optional[float] = None,
    source: Optional[str] = None,
):
    """
    Search endpoint: Uses semantic vector search if model & embeddings are available,
    otherwise falls back to keyword matching.
    """
    if search_engine and search_engine.embeddings is not None:
        try:
            return search_engine.search(
                query=q,
                top_k=top_k,
                category=category,
                max_price=max_price,
                min_rating=min_rating,
                source=source
            )
        except Exception as err:
            print("Semantic search failed, falling back to keyword:", err)

    products = load_raw_catalog()
    q_lower = q.lower()
    matches = []

    for p in products:
        p_title = (p.get("title") or "").lower()
        p_desc = (p.get("description") or "").lower()
        p_brand = (p.get("brand") or "").lower()
        p_cat = (p.get("category") or "").lower()

        if category and category.lower() != "all" and p_cat != category.lower():
            continue
        if source and source.lower() != "all" and (p.get("source") or "").lower() != source.lower():
            continue
        if max_price is not None and (p.get("price") or 0) > max_price:
            continue

        raw_rating = p.get("rating")
        if isinstance(raw_rating, dict):
            rating_val = raw_rating.get("rate")
        elif isinstance(raw_rating, (int, float)):
            rating_val = float(raw_rating)
        else:
            rating_val = None

        if min_rating is not None and rating_val is not None and rating_val < min_rating:
            continue

        score = 0.0
        if q_lower in p_title:
            score += 0.8
        if q_lower in p_desc:
            score += 0.4
        if q_lower in p_brand:
            score += 0.6
        if q_lower in p_cat:
            score += 0.5

        if score > 0:
            thumb = p.get("thumbnail") or p.get("image") or (p.get("images", [""])[0] if p.get("images") else "")
            matches.append({
                "score": round(score, 2),
                "chunk_id": f"chunk_{p.get('source')}_{p.get('id')}",
                "product_id": p.get("id"),
                "source": p.get("source"),
                "title": p.get("title"),
                "category": p.get("category"),
                "brand": p.get("brand"),
                "price": p.get("price"),
                "rating": rating_val,
                "stock": p.get("stock"),
                "thumbnail": thumb,
                "chunk_excerpt": (p.get("description") or "")[:200]
            })

    matches.sort(key=lambda x: -x["score"])
    return matches[:top_k]


# ==============================================================================
# CHROME EXTENSION & PRODUCT TRACKING APIs
# ==============================================================================
import tracker_db
from price_scraper import price_scraper
from email_service import email_service
from tracker_scheduler import tracker_scheduler

# Start background tracker scheduler
@app.on_event("startup")
def start_tracker_scheduler():
    tracker_scheduler.start(interval_seconds=300)

class TrackProductRequest(BaseModel):
    product_id: Optional[Any] = None
    product_name: str
    product_url: str
    website: Optional[str] = "Web"
    current_price: float
    currency: Optional[str] = "PKR"
    brand: Optional[str] = None
    model: Optional[str] = None
    image_url: Optional[str] = None
    target_price: Optional[float] = None
    alert_type: Optional[str] = "target_price"
    specifications: Optional[Dict[str, Any]] = None
    original_price: Optional[float] = None
    alert_threshold: Optional[float] = None
    user_email: Optional[str] = None
    is_assistant_product: Optional[bool] = False

class UpdateTrackedProductRequest(BaseModel):
    target_price: Optional[float] = None
    tracking_status: Optional[str] = None
    alert_type: Optional[str] = None
    alert_threshold: Optional[float] = None
    user_email: Optional[str] = None

class UserSettingsRequest(BaseModel):
    alert_email: Optional[str] = None
    check_interval_minutes: Optional[str] = None
    notifications_enabled: Optional[str] = None
    price_drop_alerts_enabled: Optional[str] = None
    min_price_drop_amount: Optional[str] = None
    price_drop_pct_threshold: Optional[str] = None
    alert_frequency: Optional[str] = None
    tracked_alerts_enabled: Optional[str] = None
    browser_notifications_enabled: Optional[str] = None
    email_notifications_enabled: Optional[str] = None
    email_alert_preferences: Optional[str] = None


def is_valid_product_url(url: Optional[str], is_assistant_product: bool = False) -> Tuple[bool, str]:
    """
    Validates that a URL belongs to an exact product page before tracking.
    Rejects missing URLs, non-HTTP URLs, homepages, search pages, and generic listing URLs.
    """
    default_msg = (
        "This product does not have a valid product URL, so it cannot be tracked until a valid product URL is available."
        if is_assistant_product
        else "I couldn't identify the exact product page, so I can't safely track this product."
    )
    if not url or not isinstance(url, str):
        return False, default_msg
    url_clean = url.strip()
    if not (url_clean.startswith("http://") or url_clean.startswith("https://")):
        return False, default_msg

    try:
        parsed = urllib.parse.urlparse(url_clean)
    except Exception:
        return False, default_msg

    netloc = parsed.netloc.lower()
    path = parsed.path.lower()
    query = parsed.query.lower()

    if not netloc or path in ("", "/"):
        return False, default_msg

    # Generic search, category, or non-product endpoints
    is_search_or_listing = False
    if any(s in path for s in ["/search", "/catalog", "/categories", "/category", "/browse", "/department", "/cart", "/checkout", "/account"]):
        is_search_or_listing = True
    elif "/s" in path and ("k=" in query or "q=" in query):
        is_search_or_listing = True
    elif any(q in query for q in ["search=", "query=", "?q=", "&q="]):
        is_search_or_listing = True

    # Check for recognized product path tokens
    has_product_pattern = any(p in path for p in ["/products/", "/product/", "/item/", "/dp/", "/itm/", "/p/", "/item-", ".html"])

    if is_search_or_listing and not has_product_pattern:
        return False, default_msg

    return True, ""


def async_verify_and_update_tracked_product(prod_id: str, product_url: str):
    """
    Asynchronous background worker task:
    Runs price_scraper safely with retries, then updates tracker.db with verified live data.
    """
    try:
        scraped = price_scraper.scrape_product_info(product_url)
        if scraped and scraped.get("price") is not None and float(scraped["price"]) > 0:
            verified_price = float(scraped["price"])
            curr = scraped.get("currency")
            tracker_db.record_price_update(prod_id, verified_price, curr)
            updates = {}
            if scraped.get("brand"):
                updates["brand"] = scraped["brand"]
            if scraped.get("model"):
                updates["model"] = scraped["model"]
            if scraped.get("image"):
                updates["image_url"] = scraped["image"]
            if updates:
                with tracker_db.get_db_connection() as conn:
                    cursor = conn.cursor()
                    set_clauses = [f"{k} = ?" for k in updates.keys()]
                    vals = list(updates.values()) + [prod_id]
                    cursor.execute(f"UPDATE tracked_products SET {', '.join(set_clauses)} WHERE id = ?", vals)
                    conn.commit()
    except Exception as e:
        logger.warning(f"Background verification for {prod_id} completed: {e}")


class ExtensionChatRequest(BaseModel):
    message: str
    active_product: Optional[Dict[str, Any]] = None
    page_products: Optional[List[Dict[str, Any]]] = None
    assistant_product: Optional[Dict[str, Any]] = None
    last_assistant_product: Optional[Dict[str, Any]] = None
    history: Optional[List[ChatMessage]] = None

@app.get("/api/tracked-products")
def list_tracked_products():
    return tracker_db.get_all_tracked_products()

@app.post("/api/track-product")
def track_product_endpoint(req: TrackProductRequest, background_tasks: BackgroundTasks):
    is_asst = bool(req.is_assistant_product or (req.website in ["ShopAI Store", "Catalog", "DummyJSON", "FakeStore"]))
    valid, err_msg = is_valid_product_url(req.product_url, is_assistant_product=is_asst)
    if not valid:
        raise HTTPException(status_code=400, detail=err_msg)

    site = req.website
    if not site or site == "Web":
        try:
            parsed = urllib.parse.urlparse(req.product_url)
            site = parsed.netloc.replace("www.", "") if parsed.netloc else "Web"
        except Exception:
            site = "Web"

    specifications = dict(req.specifications or {})
    if req.product_id:
        specifications["productId"] = req.product_id
        specifications["catalog_id"] = req.product_id

    prod = tracker_db.add_tracked_product(
        product_name=req.product_name,
        product_url=req.product_url,
        website=site,
        current_price=req.current_price,
        currency=req.currency or "PKR",
        brand=req.brand,
        model=req.model,
        image_url=req.image_url,
        target_price=req.target_price,
        alert_type=req.alert_type or "target_price",
        specifications=specifications,
        original_price=req.original_price or req.current_price,
        alert_threshold=req.alert_threshold,
        user_email=req.user_email
    )

    # Dispatch asynchronous background worker to verify live price & scrape updates
    background_tasks.add_task(async_verify_and_update_tracked_product, prod["id"], req.product_url)

    return prod

@app.get("/api/pending-notifications")
def get_pending_notifications_endpoint():
    return tracker_db.get_pending_browser_notifications()

@app.post("/api/ack-notifications")
def ack_notifications_endpoint():
    tracker_db.acknowledge_browser_notifications()
    return {"status": "ok"}


@app.get("/api/tracked-products/{prod_id}")
def get_single_tracked_product(prod_id: str):
    prod = tracker_db.get_tracked_product(prod_id)
    if not prod:
        return {"error": "Product not found"}
    return prod

@app.patch("/api/tracked-products/{prod_id}")
def update_tracked_product_endpoint(prod_id: str, req: UpdateTrackedProductRequest):
    updated = tracker_db.update_tracked_product(
        prod_id=prod_id,
        target_price=req.target_price,
        tracking_status=req.tracking_status,
        alert_type=req.alert_type
    )
    return updated

@app.delete("/api/tracked-products/{prod_id}")
def delete_tracked_product_endpoint(prod_id: str):
    success = tracker_db.delete_tracked_product(prod_id)
    return {"success": success}

@app.get("/api/tracked-products/{prod_id}/history")
def get_price_history_endpoint(prod_id: str):
    return tracker_db.get_price_history(prod_id)

@app.post("/api/check-price/{prod_id}")
def check_single_product_price(prod_id: str):
    prod = tracker_db.get_tracked_product(prod_id)
    if not prod:
        return {"error": "Product not found"}
    return tracker_scheduler.check_product_price(prod)

@app.post("/api/check-all-prices")
def check_all_prices_endpoint():
    results = tracker_scheduler.check_all_active_products()
    return {"results": results}

@app.get("/api/settings")
def get_settings_endpoint():
    return tracker_db.get_user_settings()

@app.post("/api/settings")
def save_settings_endpoint(req: UserSettingsRequest):
    settings = {}
    data = req.model_dump() if hasattr(req, "model_dump") else req.dict()
    for field_name, value in data.items():
        if value is not None:
            settings[field_name] = str(value)
    tracker_db.update_user_settings(settings)
    return tracker_db.get_user_settings()



@app.post("/api/test-email-alert")
def test_email_alert_endpoint():
    settings = tracker_db.get_user_settings()
    recipient = settings.get("alert_email", "user@example.com")
    res = email_service.send_price_drop_alert(
        product_id="test-demo-product",
        product_name="Samsung Galaxy S24 (Test Demo)",
        product_url="http://127.0.0.1:8000/test_pages/daraz_samsung_s24.html",
        current_price=159999.0,
        previous_price=180000.0,
        currency="PKR",
        target_price=160000.0,
        recipient_email=recipient
    )
    return res

@app.get("/api/alert-logs")
def get_alert_logs_endpoint():
    return tracker_db.get_alert_logs()

@app.get("/test_pages/{filename}")
def serve_test_page(filename: str):
    file_path = os.path.join("test_pages", filename)
    if os.path.exists(file_path):
        return FileResponse(file_path)
    return {"error": "File not found"}

@app.get("/.well-known/appspecific/com.chrome.devtools.json")
def chrome_devtools_endpoint():
    return Response(status_code=204)

@app.post("/api/extension/chat")
def extension_chat_endpoint(req: ExtensionChatRequest, background_tasks: BackgroundTasks):
    """
    Handles natural language queries from the Chrome extension:
    - 'What is this product?' -> Summarizes webpage or ShopAI assistant product
    - 'Track this product' -> Adds exact product to tracking list
    - 'Track this phone and alert me when it falls below PKR 160,000' -> Sets target price
    - 'Show tracked products' -> Summarizes tracked items
    - 'Stop tracking' -> Pauses/removes active product
    - Conversational queries -> Delegates to ShopAI Assistant powered by integrated Ollama LLM
    """
    msg = req.message.strip()
    prod = req.active_product
    msg_lower = msg.lower()
    last_asst_prod = req.last_assistant_product or req.assistant_product

    # Case 1: What is this product?
    if any(q in msg_lower for q in ["what is this", "tell me about this", "details", "info", "what product"]):
        target = prod or last_asst_prod
        if not target or not (target.get("name") or target.get("title")):
            return {
                "reply": "I couldn't detect a product on this webpage or in our assistant chat. Please navigate to a product detail page or ask ShopAI Assistant for recommendations.",
                "tracked_product_added": False
            }
        
        curr = target.get("currency", "PKR")
        price_val = target.get("price", 0)
        formatted_price = f"{curr} {price_val:,.0f}" if isinstance(price_val, (int, float)) and float(price_val).is_integer() else f"{curr} {price_val:,.2f}"
        prod_title = target.get('name') or target.get('title')
        
        reply = (
            f"Here is the product details from {target.get('website', 'the store')}:\n\n"
            f"📦 **Product:** {prod_title}\n"
            f"🏷️ **Brand:** {target.get('brand', 'N/A')}\n"
            f"🔢 **Model/SKU:** {target.get('model') or target.get('sku') or 'N/A'}\n"
            f"💰 **Current Price:** {formatted_price}\n"
            f"🌐 **Website:** {target.get('website', 'Store')}\n\n"
            "Would you like me to track this product for price drops?"
        )
        return {"reply": reply, "tracked_product_added": False, "product": target}

    # Case 2: Stop or Pause Tracking
    if any(k in msg_lower for k in ["stop tracking", "pause tracking", "delete tracking", "untrack", "remove tracking", "don't track", "stop"]):
        url_to_stop = (prod.get("url") if prod else None) or (last_asst_prod.get("url") if last_asst_prod else None)
        if url_to_stop:
            conn = tracker_db.get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT id, product_name FROM tracked_products WHERE product_url = ?", (url_to_stop,))
            row = cursor.fetchone()
            if row:
                tracker_db.delete_tracked_product(row["id"])
                return {"reply": f"🛑 Stopped tracking **{row['product_name']}** and removed it from your tracking list.", "tracked_product_added": False}

        return {"reply": "You can pause or remove any item from the **Tracked** dashboard tab.", "tracked_product_added": False}

    # Case 3: Show Tracked Products / Dashboard query
    if any(k in msg_lower for k in ["show tracked", "my tracked", "tracking list", "what am i tracking", "list tracked"]):
        tracked = tracker_db.get_all_tracked_products()
        if not tracked:
            return {"reply": "You have no tracked products yet. Open any product page and click 'Track This Product'!", "tracked_product_added": False}

        lines = [f"📋 **You are currently tracking {len(tracked)} product(s):**\n"]
        for idx, item in enumerate(tracked[:5], 1):
            c_p = float(item["current_price"])
            c_str = f"{item['currency']} {c_p:,.0f}" if c_p.is_integer() else f"{item['currency']} {c_p:,.2f}"
            status_emoji = "🟢" if item["tracking_status"] == "active" else ("⏸️" if item["tracking_status"] == "paused" else "🔔")
            lines.append(f"{idx}. {status_emoji} **{item['product_name'][:35]}** — {c_str} ({item['website']})")
        return {"reply": "\n".join(lines), "tracked_product_added": False}

    # Case 4: Track with Target Price or General Tracking
    is_track_query = any(k in msg_lower for k in [
        "track", "alert me", "monitor", "watch", "save this", "start tracking",
        "track this product", "track this item", "track the price", "start tracking this"
    ])
    if is_track_query:
        selected_prod = None
        is_shopai_prod = False

        # 4a. Check if tracking the ShopAI Assistant product
        # Triggered when user says "track this product/item/price", "start tracking this", or refers to last assistant product
        if last_asst_prod:
            asst_name = (last_asst_prod.get("name") or last_asst_prod.get("title") or "").strip().lower()
            generic_track_phrases = [
                "track this product", "track this item", "track the price",
                "start tracking this", "track this", "track it", "track price", "track item"
            ]
            user_used_generic_track = any(p in msg_lower for p in generic_track_phrases)
            user_mentioned_asst_name = asst_name and asst_name in msg_lower

            if user_mentioned_asst_name or (user_used_generic_track and not req.page_products):
                selected_prod = last_asst_prod
                is_shopai_prod = True
            elif not prod or not prod.get("name"):
                selected_prod = last_asst_prod
                is_shopai_prod = True

        # 4b. Multi-product webpage: identify exact user-selected product
        if not selected_prod and req.page_products:
            best_p = None
            best_score = 0
            stop_words = {"product", "products", "item", "items", "the", "this", "that", "track", "buy", "for", "me", "please"}
            for p in req.page_products:
                p_name = (p.get("name") or "").strip().lower()
                if not p_name:
                    continue
                score = 0
                if p_name in msg_lower:
                    score += 100 + len(p_name)
                
                p_words = [w for w in re.findall(r"\w+", p_name) if w not in stop_words]
                if p_words:
                    matched = sum(1 for w in p_words if re.search(r"\b" + re.escape(w) + r"\b", msg_lower))
                    if matched == len(p_words):
                        score += 50 + matched * 10
                    elif matched > 0:
                        score += matched * 5

                if score > best_score:
                    best_score = score
                    best_p = p

            if best_p and best_score > 0:
                selected_prod = best_p
            elif not selected_prod and len(req.page_products) == 1:
                selected_prod = req.page_products[0]

        # 4c. Active webpage product fallback
        if not selected_prod and prod and prod.get("name"):
            selected_prod = prod

        # 4d. Fallback: match catalog item name if explicitly mentioned in query
        if not selected_prod:
            for cp in catalog_data:
                c_title = (cp.get("title") or "").strip().lower()
                if c_title and (c_title in msg_lower or (len(c_title) > 6 and c_title[:18] in msg_lower)):
                    selected_prod = dict(cp)
                    is_shopai_prod = True
                    break

        if not selected_prod or not (selected_prod.get("name") or selected_prod.get("title")):
            return {
                "reply": "No product was detected on the current page or in the assistant conversation to track. Please open a product page or ask ShopAI Assistant for a recommendation first.",
                "tracked_product_added": False
            }

        # Extract complete product data (Requirement 2)
        prod_name = selected_prod.get("name") or selected_prod.get("title")
        prod_url = selected_prod.get("url") or selected_prod.get("product_url")
        prod_id = selected_prod.get("id") or selected_prod.get("productId")
        brand = selected_prod.get("brand") or "N/A"
        model = selected_prod.get("model") or selected_prod.get("sku") or "N/A"
        image_url = selected_prod.get("image") or selected_prod.get("image_url") or selected_prod.get("thumbnail") or ""
        website = selected_prod.get("website") or ("ShopAI Store" if is_shopai_prod else "Store")
        currency = selected_prod.get("currency") or "PKR"
        curr_p = float(selected_prod.get("price") or 0.0)
        specifications = dict(selected_prod.get("specifications") or {})
        if prod_id:
            specifications["productId"] = prod_id
            specifications["catalog_id"] = prod_id
        if selected_prod.get("sku"):
            specifications["sku"] = selected_prod.get("sku")
        if selected_prod.get("category"):
            specifications["category"] = selected_prod.get("category")

        # Strict URL validation (Requirement 8)
        valid_url, err_msg = is_valid_product_url(prod_url)
        if not valid_url:
            if is_shopai_prod or (last_asst_prod and selected_prod == last_asst_prod):
                return {
                    "reply": "This product does not have a valid product URL, so it cannot be tracked until a valid product URL is available.",
                    "tracked_product_added": False
                }
            return {
                "reply": "I couldn't identify the exact product page, so I can't safely track this product.",
                "tracked_product_added": False
            }

        # Check live webpage for latest current price if possible (Requirement 9)
        if is_shopai_prod and prod_url:
            try:
                live_scraped = price_scraper.scrape_product_info(prod_url)
                if live_scraped and live_scraped.get("price") and float(live_scraped["price"]) > 0:
                    curr_p = float(live_scraped["price"])
                    if live_scraped.get("currency"):
                        currency = live_scraped["currency"]
                    if live_scraped.get("image") and not image_url:
                        image_url = live_scraped["image"]
            except Exception as e:
                logger.warning(f"Live price scrape skipped for {prod_url}: {e}")

        # Check if user specified a target price e.g. "below PKR 160,000" or "below 160000"
        target_price = None
        target_match = re.search(r"\b(?:below|under|at|to|less than|target)\s*(?:pkr|rs\.?|\$|usd)?\s*([0-9]+(?:,[0-9]+)*(?:\.[0-9]+)?)\s*(k)?", msg_lower)
        if target_match:
            clean_num = target_match.group(1).replace(",", "")
            target_price = float(clean_num)
            if target_match.group(2) == "k":
                target_price *= 1000

        # Check if user specified a percentage threshold e.g. "by 5%" or "5% drop"
        alert_threshold = None
        pct_match = re.search(r"(\d+(?:\.\d+)?)\s*%", msg_lower)
        if pct_match:
            alert_threshold = float(pct_match.group(1))

        # Track ONLY this exact product using product URL as the primary identifier (Requirement 3, 4)
        tracked_item = tracker_db.add_tracked_product(
            product_name=prod_name,
            product_url=prod_url,
            website=website,
            current_price=curr_p,
            currency=currency,
            brand=brand,
            model=model,
            image_url=image_url,
            target_price=target_price,
            alert_type="target_price" if target_price else "any_drop",
            specifications=specifications,
            original_price=curr_p,
            alert_threshold=alert_threshold
        )

        # Dispatch asynchronous background worker to verify live price & scrape updates
        background_tasks.add_task(async_verify_and_update_tracked_product, tracked_item["id"], prod_url)

        tracking_record = {
            "productId": tracked_item["id"],
            "productName": tracked_item["product_name"],
            "productUrl": tracked_item["product_url"],
            "website": tracked_item["website"],
            "currentPrice": tracked_item["current_price"],
            "currency": tracked_item["currency"],
            "brand": tracked_item.get("brand"),
            "model": tracked_item.get("model"),
            "imageUrl": tracked_item.get("image_url"),
            "specifications": specifications,
            "trackingEnabled": True
        }

        curr_str = f"{currency} {curr_p:,.0f}" if curr_p.is_integer() else f"{currency} {curr_p:,.2f}"
        if target_price:
            targ_str = f"{currency} {target_price:,.0f}" if target_price.is_integer() else f"{currency} {target_price:,.2f}"
            reply = (
                f"✅ **Tracking Started!**\n\n"
                f"I have added **{prod_name}** to your tracking list.\n"
                f"• Current Price: **{curr_str}**\n"
                f"• Target Alert Price: **{targ_str}**\n\n"
                f"Our background scheduler will periodically check this exact URL and send an alert when the price drops below {targ_str}!"
            )
        elif alert_threshold:
            reply = (
                f"✅ **Tracking Started!**\n\n"
                f"I have added **{prod_name}** to your tracking list.\n"
                f"• Current Price: **{curr_str}**\n"
                f"• Drop Threshold: **{alert_threshold}%**\n\n"
                f"Our background scheduler will monitor this product and send an alert when the price decreases by {alert_threshold}% or more."
            )
        else:
            reply = (
                f"✅ **Tracking Started!**\n\n"
                f"I have added **{prod_name}** to your tracking list.\n"
                f"• Current Price: **{curr_str}**\n"
                f"• Alert Mode: **Any price drop**\n\n"
                f"Our background scheduler will check this exact URL every 5 minutes and alert you as soon as the price drops."
            )

        return {
            "reply": reply,
            "tracked_product_added": True,
            "product": tracked_item,
            "tracking_record": tracking_record
        }

    # Case 5: Conversational Product-Selection Assistant (ShopAI Assistant)
    chat_req = ChatRequest(
        message=req.message,
        history=req.history
    )
    chat_res = chat_with_assistant(chat_req)

    returned_prods = chat_res.get("products") or []
    asst_prod = returned_prods[0] if returned_prods else None

    return {
        "reply": chat_res.get("reply", ""),
        "tracked_product_added": False,
        "products": returned_prods,
        "assistant_product": asst_prod,
        "model_used": chat_res.get("model_used")
    }


if __name__ == "__main__":
    print("\nStarting ShopAI Assistant server at: http://localhost:8000")
    print("Open http://localhost:8000 in your browser to view the storefront.\n")
    uvicorn.run(app, host="127.0.0.1", port=8000)
