/**
 * ShopAI Chrome Extension - Dedicated Options Controller
 * Strictly handles Alert Settings and Notification Settings
 */

document.addEventListener("DOMContentLoaded", async () => {
  let apiUrl = "http://localhost:8000";

  // Elements
  const serverStatus = document.getElementById("server-status");
  const statusText = document.getElementById("status-text");
  const optionsForm = document.getElementById("options-form");

  const optPriceDropAlerts = document.getElementById("opt-price-drop-alerts");
  const optTrackedAlerts = document.getElementById("opt-tracked-alerts-enabled");
  const optMinDropPct = document.getElementById("opt-min-drop-pct");
  const optMinDropAmount = document.getElementById("opt-min-drop-amount");
  const optAlertFrequency = document.getElementById("opt-alert-frequency");

  const optBrowserNotifications = document.getElementById("opt-browser-notifications");
  const optEmailNotifications = document.getElementById("opt-email-notifications");
  const optAlertEmail = document.getElementById("opt-alert-email");
  const optEmailPref = document.getElementById("opt-email-pref");
  const optApiUrl = document.getElementById("opt-api-url");

  const btnTestEmail = document.getElementById("btn-test-email");
  const testEmailMsg = document.getElementById("test-email-msg");
  const saveStatusMsg = document.getElementById("save-status-msg");

  // Check Backend Status
  async function checkBackend() {
    try {
      const res = await fetch(`${apiUrl}/api/settings`);
      if (res.ok) {
        serverStatus.className = "server-badge connected";
        statusText.textContent = "Backend Connected";
        return true;
      }
    } catch (e) {}
    serverStatus.className = "server-badge offline";
    statusText.textContent = "Backend Offline";
    return false;
  }

  // Load Settings
  async function loadAllSettings() {
    if (chrome.storage && chrome.storage.local) {
      const stored = await chrome.storage.local.get(["apiUrl"]);
      if (stored.apiUrl) apiUrl = stored.apiUrl;
    }

    try {
      const res = await fetch(`${apiUrl}/api/settings`);
      if (res.ok) {
        const data = await res.json();
        // Alert Settings
        if (data.price_drop_alerts_enabled !== undefined) {
          optPriceDropAlerts.checked = data.price_drop_alerts_enabled === "true";
        }
        if (data.tracked_alerts_enabled !== undefined) {
          optTrackedAlerts.checked = data.tracked_alerts_enabled === "true";
        }
        if (data.price_drop_pct_threshold) optMinDropPct.value = data.price_drop_pct_threshold;
        if (data.min_price_drop_amount) optMinDropAmount.value = data.min_price_drop_amount;
        if (data.alert_frequency) optAlertFrequency.value = data.alert_frequency;

        // Notification Settings
        if (data.browser_notifications_enabled !== undefined) {
          optBrowserNotifications.checked = data.browser_notifications_enabled === "true";
        }
        if (data.email_notifications_enabled !== undefined) {
          optEmailNotifications.checked = data.email_notifications_enabled === "true";
        }
        if (data.alert_email) optAlertEmail.value = data.alert_email;
        if (data.email_alert_preferences) optEmailPref.value = data.email_alert_preferences;
      }
    } catch (err) {
      console.warn("Could not load backend settings:", err);
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
      if (stored.apiUrl) optApiUrl.value = stored.apiUrl;
      if (stored.alertEmail && !optAlertEmail.value) optAlertEmail.value = stored.alertEmail;
      if (stored.priceDropAlerts !== undefined) optPriceDropAlerts.checked = stored.priceDropAlerts;
      if (stored.trackedAlerts !== undefined) optTrackedAlerts.checked = stored.trackedAlerts;
      if (stored.minDropPct) optMinDropPct.value = stored.minDropPct;
      if (stored.minDropAmount) optMinDropAmount.value = stored.minDropAmount;
      if (stored.alertFrequency) optAlertFrequency.value = stored.alertFrequency;
      if (stored.browserNotifications !== undefined) optBrowserNotifications.checked = stored.browserNotifications;
      if (stored.emailNotifications !== undefined) optEmailNotifications.checked = stored.emailNotifications;
      if (stored.emailPref) optEmailPref.value = stored.emailPref;
    }
  }

  // Save Settings
  optionsForm.addEventListener("submit", async (e) => {
    e.preventDefault();

    const priceDropAlerts = optPriceDropAlerts.checked ? "true" : "false";
    const trackedAlerts = optTrackedAlerts.checked ? "true" : "false";
    const minDropPct = optMinDropPct.value;
    const minDropAmount = optMinDropAmount.value.trim();
    const alertFrequency = optAlertFrequency.value;

    const browserNotifications = optBrowserNotifications.checked ? "true" : "false";
    const emailNotifications = optEmailNotifications.checked ? "true" : "false";
    const email = optAlertEmail.value.trim();
    const emailPref = optEmailPref.value;
    const newApiUrl = optApiUrl.value.trim() || "http://localhost:8000";

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
      await fetch(`${newApiUrl}/api/settings`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });

      if (chrome.storage && chrome.storage.local) {
        await chrome.storage.local.set({
          apiUrl: newApiUrl,
          alertEmail: email,
          priceDropAlerts: optPriceDropAlerts.checked,
          trackedAlerts: optTrackedAlerts.checked,
          minDropPct: minDropPct,
          minDropAmount: minDropAmount,
          alertFrequency: alertFrequency,
          browserNotifications: optBrowserNotifications.checked,
          emailNotifications: optEmailNotifications.checked,
          emailPref: emailPref
        });
      }

      apiUrl = newApiUrl;
      saveStatusMsg.textContent = "✓ Settings saved successfully!";
      saveStatusMsg.classList.remove("hidden");
      setTimeout(() => saveStatusMsg.classList.add("hidden"), 3000);
      checkBackend();
    } catch (err) {
      alert("Error saving settings: " + err.message);
    }
  });

  // Test Email
  btnTestEmail.addEventListener("click", async () => {
    btnTestEmail.disabled = true;
    testEmailMsg.className = "alert-box hidden";

    try {
      const res = await fetch(`${apiUrl}/api/test-email-alert`, { method: "POST" });
      const data = await res.json();
      if (res.ok && data.success) {
        testEmailMsg.className = "alert-box success";
        testEmailMsg.textContent = `✅ Test price-drop alert sent to ${data.recipient || optAlertEmail.value || 'configured email'}!`;
        testEmailMsg.classList.remove("hidden");
      } else {
        testEmailMsg.className = "alert-box error";
        testEmailMsg.textContent = `❌ Email failed: ${data.message || 'Check SMTP in .env'}`;
        testEmailMsg.classList.remove("hidden");
      }
    } catch (err) {
      testEmailMsg.className = "alert-box error";
      testEmailMsg.textContent = "❌ Connection failed: " + err.message;
      testEmailMsg.classList.remove("hidden");
    } finally {
      btnTestEmail.disabled = false;
    }
  });

  await checkBackend();
  await loadAllSettings();
});
