/**
 * Google Apps Script — réception + mise en forme des signaux de l'agent boursier.
 *
 * INSTALLATION / MISE À JOUR :
 * 1. Extensions → Apps Script, colle ce code (remplace tout), sauvegarde.
 * 2. Déployer → Gérer les déploiements → crayon ✏️ → Version : Nouvelle version → Déployer.
 * 3. (Première fois) Déployer en Application Web, accès "Tout le monde".
 *
 * Le script fait un "upsert" par id (met à jour la ligne si elle existe), met en
 * forme l'en-tête, formate les montants/%, et colore en vert/rouge les gains/pertes.
 */

var HEADERS = [
  "id", "date_entree", "ticker", "figure", "score", "prix_entree", "objectif",
  "stop", "horizon_j", "mise_eur", "statut", "raison_sortie", "prix_sortie",
  "date_sortie", "jours_detenus", "resultat_pct", "plus_value_eur",
  "action_remy", "paper"
];

// Libellés lisibles affichés dans l'en-tête
var LABELS = {
  id: "ID", date_entree: "Date entrée", ticker: "Ticker", figure: "Figure",
  score: "Score /100", prix_entree: "Prix entrée", objectif: "Objectif",
  stop: "Stop", horizon_j: "Horizon (j)", mise_eur: "Mise", statut: "Statut",
  raison_sortie: "Raison sortie", prix_sortie: "Prix sortie",
  date_sortie: "Date sortie", jours_detenus: "Jours tenus",
  resultat_pct: "Résultat %", plus_value_eur: "Plus-value", action_remy: "Mon action",
  paper: "Simulé"
};

var WIDTHS = {
  id: 90, date_entree: 130, ticker: 75, figure: 110, score: 70, prix_entree: 90,
  objectif: 85, stop: 75, horizon_j: 80, mise_eur: 80, statut: 85,
  raison_sortie: 110, prix_sortie: 90, date_sortie: 130, jours_detenus: 85,
  resultat_pct: 95, plus_value_eur: 110, action_remy: 100, paper: 70
};

function col(name) { return HEADERS.indexOf(name) + 1; }

function setupSheet(sheet) {
  // En-tête lisible
  var labels = HEADERS.map(function (h) { return LABELS[h] || h; });
  sheet.getRange(1, 1, 1, HEADERS.length).setValues([labels]);

  // Style en-tête : fond navy, texte blanc, gras, centré, figé
  var header = sheet.getRange(1, 1, 1, HEADERS.length);
  header.setBackground("#1f2a44").setFontColor("#ffffff").setFontWeight("bold")
        .setHorizontalAlignment("center").setVerticalAlignment("middle");
  sheet.setFrozenRows(1);
  sheet.setRowHeight(1, 30);

  // Largeurs de colonnes
  HEADERS.forEach(function (h) {
    if (WIDTHS[h]) sheet.setColumnWidth(col(h), WIDTHS[h]);
  });

  // Formats de nombres (sur une large plage de lignes futures)
  var n = 2000;
  sheet.getRange(2, col("prix_entree"), n, 1).setNumberFormat("0.00");
  sheet.getRange(2, col("objectif"), n, 1).setNumberFormat("0.00");
  sheet.getRange(2, col("stop"), n, 1).setNumberFormat("0.00");
  sheet.getRange(2, col("prix_sortie"), n, 1).setNumberFormat("0.00");
  sheet.getRange(2, col("mise_eur"), n, 1).setNumberFormat("#,##0 \"€\"");
  sheet.getRange(2, col("resultat_pct"), n, 1).setNumberFormat("0.00 \"%\"");
  sheet.getRange(2, col("plus_value_eur"), n, 1).setNumberFormat("#,##0.00 \"€\"");
  sheet.getRange(2, col("score"), n, 1).setHorizontalAlignment("center");
  sheet.getRange(2, col("ticker"), n, 1).setFontWeight("bold");

  // Bandes alternées (lisibilité)
  try {
    sheet.getRange(1, 1, n, HEADERS.length)
         .applyRowBanding(SpreadsheetApp.BandingTheme.LIGHT_GREY, true, false);
  } catch (e) {}
}

function styleRow(sheet, rowNum, row) {
  // Couleur du résultat % et de la plus-value selon gain/perte
  ["resultat_pct", "plus_value_eur"].forEach(function (h) {
    var v = parseFloat(row[h]);
    var cell = sheet.getRange(rowNum, col(h));
    if (!isNaN(v)) {
      cell.setFontColor(v > 0 ? "#137333" : (v < 0 ? "#b00020" : "#666666"))
          .setFontWeight("bold");
    }
  });
  // Couleur de la raison de sortie
  var reason = row["raison_sortie"];
  var rc = sheet.getRange(rowNum, col("raison_sortie"));
  if (reason === "objectif") rc.setBackground("#e6f4ea");
  else if (reason === "stop") rc.setBackground("#fce8e6");
  else if (reason === "horizon") rc.setBackground("#f1f3f4");
  else rc.setBackground(null);
  // Statut
  var st = sheet.getRange(rowNum, col("statut"));
  st.setBackground(row["statut"] === "clôturé" ? "#eef0f5" : "#fff7e0");
}

function doPost(e) {
  var lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try {
    var body = JSON.parse(e.postData.contents);
    var row = body.row || {};
    var sheet = SpreadsheetApp.getActiveSpreadsheet().getSheets()[0];

    if (sheet.getLastRow() === 0) setupSheet(sheet);

    var values = HEADERS.map(function (h) {
      return row[h] !== undefined ? row[h] : "";
    });

    // Upsert par id
    var foundRow = -1;
    var numRows = sheet.getLastRow() - 1;
    if (numRows > 0 && row.id) {
      var ids = sheet.getRange(2, 1, numRows, 1).getValues();
      for (var i = 0; i < ids.length; i++) {
        if (ids[i][0] === row.id) { foundRow = i + 2; break; }
      }
    }

    var rowNum;
    if (foundRow > 0) {
      rowNum = foundRow;
    } else {
      rowNum = sheet.getLastRow() + 1;
    }
    sheet.getRange(rowNum, 1, 1, HEADERS.length).setValues([values]);
    styleRow(sheet, rowNum, row);

    return ContentService
      .createTextOutput(JSON.stringify({ ok: true, row: rowNum }))
      .setMimeType(ContentService.MimeType.JSON);
  } catch (err) {
    return ContentService
      .createTextOutput(JSON.stringify({ ok: false, error: String(err) }))
      .setMimeType(ContentService.MimeType.JSON);
  } finally {
    lock.releaseLock();
  }
}
