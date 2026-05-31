/**
 * Google Apps Script — réception des signaux de l'agent boursier.
 *
 * INSTALLATION (5 min) :
 * 1. Crée une Google Sheet vide (sheets.new).
 * 2. Menu Extensions → Apps Script.
 * 3. Colle ce code (remplace tout), sauvegarde.
 * 4. Déployer → Nouveau déploiement → type "Application Web".
 *    - Exécuter en tant que : Moi
 *    - Qui a accès : "Tout le monde"
 * 5. Copie l'URL du déploiement (https://script.google.com/macros/s/.../exec)
 *    → c'est la valeur de GOOGLE_SHEETS_WEBHOOK_URL.
 *
 * Le script fait un "upsert" par id : il met à jour la ligne du signal si elle
 * existe déjà, sinon il l'ajoute. Les résultats (J+1/3/7, P&L) se remplissent
 * donc automatiquement au fil des jours.
 */

var HEADERS = [
  "id", "date_entree", "ticker", "figure", "score", "prix_entree", "objectif",
  "stop", "horizon_j", "mise_eur", "statut", "raison_sortie", "prix_sortie",
  "date_sortie", "jours_detenus", "resultat_pct", "plus_value_eur",
  "action_remy", "paper"
];

function doPost(e) {
  var lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try {
    var body = JSON.parse(e.postData.contents);
    var row = body.row || {};
    var sheet = SpreadsheetApp.getActiveSpreadsheet().getSheets()[0];

    // En-têtes si feuille vide
    if (sheet.getLastRow() === 0) {
      sheet.appendRow(HEADERS);
      sheet.getRange(1, 1, 1, HEADERS.length).setFontWeight("bold");
    }

    var values = HEADERS.map(function (h) {
      return row[h] !== undefined ? row[h] : "";
    });

    // Recherche d'une ligne existante par id (colonne 1)
    var ids = sheet.getRange(2, 1, Math.max(sheet.getLastRow() - 1, 0), 1).getValues();
    var foundRow = -1;
    for (var i = 0; i < ids.length; i++) {
      if (ids[i][0] === row.id && row.id !== "") { foundRow = i + 2; break; }
    }

    if (foundRow > 0) {
      sheet.getRange(foundRow, 1, 1, HEADERS.length).setValues([values]);
    } else {
      sheet.appendRow(values);
    }

    return ContentService
      .createTextOutput(JSON.stringify({ ok: true }))
      .setMimeType(ContentService.MimeType.JSON);
  } catch (err) {
    return ContentService
      .createTextOutput(JSON.stringify({ ok: false, error: String(err) }))
      .setMimeType(ContentService.MimeType.JSON);
  } finally {
    lock.releaseLock();
  }
}
