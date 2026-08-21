/**
 * Gmail -> job-search-intel bridge (replaces the Cowork "application-response-tracker").
 *
 * Daily: search Gmail for ATS replies, POST them to the backend ingest endpoint.
 * Backend does classification (Claude Haiku), role matching, outcome writes,
 * and Forge firing. Idempotent server-side (message_id UNIQUE), and this script
 * only advances its watermark after a successful POST, so failed runs catch up.
 *
 * SETUP (one time, ~5 min):
 *   1. script.google.com -> New project, name it "job-search-intel bridge".
 *   2. Paste this file in. Project Settings -> Script Properties, add:
 *        BACKEND_URL = https://job-search-intel-production.up.railway.app
 *        CRON_SECRET = <value of CRON_SECRET in backend/.env>
 *   3. Run setupTrigger() once -> authorize Gmail + external-request scopes.
 *      This also creates the daily 8am trigger.
 *   4. Run testRun() once and check the Execution log for updated/forge_fired counts.
 *   5. Verify on the backend: /application-outcomes/calibration grows beyond
 *      manual entries; roles flip application_status on real ATS emails.
 */

var PROPS = PropertiesService.getScriptProperties();
var SEARCH_SENDERS =
  'from:(greenhouse-mail.io OR ashbyhq.com OR lever.co OR myworkday.com OR ' +
  'amazon.jobs OR appreview.gem.com OR smartrecruiters.com OR icims.com)';
var SUBJECT_FALLBACK =
  '(subject:("your application" OR "update on your application" OR ' +
  '"application status" OR "interview" OR "next steps"))';
var SKIP = '-from:onboarding@resend.dev -category:promotions';
var MAX_MESSAGES = 25;
var BODY_CAP = 4000;

function _searchQuery_() {
  var after = PROPS.getProperty('lastRunAfter');
  var window = after ? 'after:' + after : 'newer_than:2d'; // first run backfills 2 days
  return '(' + SEARCH_SENDERS + ' OR ' + SUBJECT_FALLBACK + ') ' + window + ' ' + SKIP;
}

function _collectEmails_() {
  var threads = GmailApp.search(_searchQuery_(), 0, MAX_MESSAGES);
  var out = [];
  for (var t = 0; t < threads.length && out.length < MAX_MESSAGES; t++) {
    var msgs = threads[t].getMessages();
    for (var m = 0; m < msgs.length && out.length < MAX_MESSAGES; m++) {
      var msg = msgs[m];
      out.push({
        message_id: msg.getId(),
        from: msg.getFrom(),
        subject: msg.getSubject(),
        body: (msg.getPlainBody() || '').slice(0, BODY_CAP),
        date: msg.getDate().toISOString(),
      });
    }
  }
  return out;
}

function runBridge() {
  var url = PROPS.getProperty('BACKEND_URL');
  var secret = PROPS.getProperty('CRON_SECRET');
  if (!url || !secret) throw new Error('Set BACKEND_URL and CRON_SECRET in Script Properties');

  var emails = _collectEmails_();
  if (!emails.length) {
    Logger.log('bridge: no candidate messages');
    return { skipped: true };
  }

  var resp = UrlFetchApp.fetch(url + '/application-updates/ingest', {
    method: 'post',
    contentType: 'application/json',
    headers: { Authorization: 'Bearer ' + secret },
    payload: JSON.stringify({ emails: emails }),
    muteHttpExceptions: true,
  });
  var body = resp.getContentText();
  if (resp.getResponseCode() !== 200) {
    // Do NOT advance the watermark -> next run retries the same window.
    throw new Error('ingest failed ' + resp.getResponseCode() + ': ' + body.slice(0, 300));
  }
  // Watermark = now minus 1h overlap; server dedups by message_id anyway.
  PROPS.setProperty(
    'lastRunAfter',
    Utilities.formatDate(new Date(Date.now() - 3600 * 1000), 'UTC', 'yyyy/MM/dd')
  );
  Logger.log('bridge: sent ' + emails.length + ' -> ' + body);
  return JSON.parse(body);
}

/** Run once manually from the editor to verify end-to-end. */
function testRun() {
  Logger.log(JSON.stringify(runBridge()));
}

/** Creates (or replaces) the daily 8am trigger. Run once during setup. */
function setupTrigger() {
  ScriptApp.getProjectTriggers()
    .filter(function (t) { return t.getHandlerFunction() === 'runBridge'; })
    .forEach(function (t) { ScriptApp.deleteTrigger(t); });
  ScriptApp.newTrigger('runBridge').timeBased().everyDays(1).atHour(8).create();
  Logger.log('daily 8am trigger created');
}
