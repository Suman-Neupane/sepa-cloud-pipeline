"""
Interactive Visual Operations Dashboard for SEPA Cloud Pipeline.

Connects to the local Official AWS Emulator on port 9297:
- Monitors live queue depths (Main Queue & Dead-Letter Queue).
- Displays DynamoDB compliance audit ledger in real-time.
- Provides 1-click test simulation buttons:
    * Standard Invoice (€1,190.00 -> APPROVED)
    * High-Value AML Invoice (€23,800.00 -> FLAGGED_AML + SNS alert)
    * Poison-Pill Corrupted Invoice (Negative VAT/Bad IBAN -> DLQ isolation)
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import urllib3
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from src.config import AppConfig
from src.processor import InvoiceEventProcessor

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = FastAPI(title="SEPA Cloud-Native FinTech Dashboard")
config = AppConfig()
processor = InvoiceEventProcessor(config=config)


@app.get("/api/status")
def get_system_status() -> dict[str, Any]:
    """Fetch live counts and state from AWS Emulator (SQS, DynamoDB, S3)."""
    emulator_healthy = False
    try:
        http = urllib3.PoolManager(cert_reqs="CERT_NONE")
        resp = http.request(
            "GET", f"{config.aws_endpoint_url}/__admin/health", timeout=1.0
        )
        emulator_healthy = resp.status == 200
    except Exception:
        emulator_healthy = False

    main_q_count = 0
    dlq_count = 0
    if emulator_healthy:
        try:
            main_url = processor._get_queue_url(config.sqs_queue_name)
            attr = processor.sqs.get_queue_attributes(
                QueueUrl=main_url,
                AttributeNames=[
                    "ApproximateNumberOfMessages",
                    "ApproximateNumberOfMessagesNotVisible",
                ],
            ).get("Attributes", {})
            main_q_count = int(attr.get("ApproximateNumberOfMessages", 0))

            dlq_url = processor._get_queue_url(config.sqs_dlq_name)
            dlq_attr = processor.sqs.get_queue_attributes(
                QueueUrl=dlq_url,
                AttributeNames=["ApproximateNumberOfMessages"],
            ).get("Attributes", {})
            dlq_count = int(dlq_attr.get("ApproximateNumberOfMessages", 0))
        except Exception:
            pass

    audit_records = []
    if emulator_healthy:
        try:
            table = processor.dynamodb.Table(config.dynamodb_table_name)
            items = table.scan().get("Items", [])
            # Sort by processed_at descending
            audit_records = sorted(
                items, key=lambda x: str(x.get("processed_at", "")), reverse=True
            )
        except Exception:
            audit_records = []

    aml_count = sum(
        1 for r in audit_records if r.get("compliance_status") == "FLAGGED_AML"
    )
    approved_count = sum(
        1 for r in audit_records if r.get("compliance_status") == "APPROVED"
    )

    return {
        "emulator_healthy": emulator_healthy,
        "endpoint": config.aws_endpoint_url,
        "region": config.aws_region,
        "main_queue_count": main_q_count,
        "dlq_count": dlq_count,
        "total_audited": len(audit_records),
        "approved_count": approved_count,
        "aml_count": aml_count,
        "records": audit_records[:25],
    }


@app.post("/api/simulate/{scenario}")
def simulate_invoice(scenario: str) -> dict[str, Any]:
    """1-click simulation trigger."""
    inv_id = f"INV-{uuid.uuid4().hex[:8].upper()}"

    if scenario == "standard":
        data = {
            "invoice_id": inv_id,
            "sender_iban": "DE89370400440532013000",
            "recipient_iban": "DE02120300000000202051",
            "net_amount": "1000.00",
            "vat_amount": "190.00",
            "gross_amount": "1190.00",
            "currency": "EUR",
        }
    elif scenario == "aml":
        data = {
            "invoice_id": inv_id,
            "sender_iban": "DE89370400440532013000",
            "recipient_iban": "DE02120300000000202051",
            "net_amount": "20000.00",
            "vat_amount": "3800.00",
            "gross_amount": "23800.00",
            "currency": "EUR",
        }
    elif scenario == "poison":
        data = {
            "invoice_id": inv_id,
            "sender_iban": "INVALID_IBAN_999",
            "recipient_iban": "DE02120300000000202051",
            "net_amount": "-500.00",
            "vat_amount": "0.00",
            "gross_amount": "-500.00",
            "currency": "EUR",
        }
    else:
        return {"error": f"Unknown scenario '{scenario}'"}

    # 1. Upload to S3
    s3_key = f"invoices/{inv_id}.json"
    processor.s3.put_object(
        Bucket=config.s3_bucket_name,
        Key=s3_key,
        Body=json.dumps(data).encode("utf-8"),
    )

    # 2. Enqueue event in SQS
    main_url = processor._get_queue_url(config.sqs_queue_name)
    processor.sqs.send_message(
        QueueUrl=main_url,
        MessageBody=json.dumps({"bucket": config.s3_bucket_name, "s3_key": s3_key}),
    )

    # 3. For standard & AML, process immediately. For poison pill, execute 3 retries to show DLQ!
    if scenario in ("standard", "aml"):
        proc_result = processor.process_single_message()
    else:
        # Simulate 3 failed processing attempts
        for _ in range(3):
            proc_result = processor.process_single_message()

    return {
        "scenario": scenario,
        "invoice_id": inv_id,
        "input_data": data,
        "processor_result": proc_result,
    }


@app.get("/", response_class=HTMLResponse)
def render_dashboard() -> str:
    """Render the responsive Tailwind HTML dashboard."""
    return """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>SEPA FinTech Cloud Operations Dashboard</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body class="bg-slate-950 text-slate-100 min-h-screen font-sans antialiased">
  
  <!-- Navigation Header -->
  <header class="border-b border-slate-800 bg-slate-900/80 backdrop-blur sticky top-0 z-50">
    <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4 flex flex-wrap justify-between items-center gap-4">
      <div class="flex items-center space-x-3">
        <div class="h-10 w-10 rounded-xl bg-gradient-to-tr from-blue-600 to-indigo-500 flex items-center justify-center shadow-lg shadow-indigo-500/20">
          <svg class="h-6 w-6 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z" />
          </svg>
        </div>
        <div>
          <h1 class="text-xl font-bold tracking-tight text-white flex items-center gap-2">
            SEPA Cloud-Native Pipeline
            <span class="text-xs font-medium px-2 py-0.5 rounded-full bg-blue-500/10 text-blue-400 border border-blue-500/20">eu-central-1</span>
          </h1>
          <p class="text-xs text-slate-400">German/EU FinTech Event Processor & Anti-Money Laundering Guard</p>
        </div>
      </div>
      
      <!-- Live Status Badge -->
      <div class="flex items-center space-x-4">
        <div id="emulator-pill" class="flex items-center gap-2 text-xs font-semibold px-3 py-1.5 rounded-full bg-slate-800 border border-slate-700 text-slate-300">
          <span class="h-2 w-2 rounded-full bg-slate-500 animate-ping"></span>
          Checking AWS Emulator...
        </div>
        <button onclick="refreshData()" class="p-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 transition text-xs flex items-center gap-1 border border-slate-700">
          <svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
          </svg>
          Refresh
        </button>
      </div>
    </div>
  </header>

  <main class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-8">
    
    <!-- Top KPI Grid -->
    <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
      <div class="bg-slate-900 border border-slate-800 rounded-2xl p-5 shadow-sm">
        <div class="text-xs font-medium text-slate-400">Total Invoices Audited</div>
        <div id="stat-total" class="text-3xl font-extrabold text-white mt-2">--</div>
        <div class="text-[11px] text-slate-500 mt-1">Stored in Amazon DynamoDB</div>
      </div>

      <div class="bg-slate-900 border border-slate-800 rounded-2xl p-5 shadow-sm">
        <div class="text-xs font-medium text-slate-400">Approved Invoices</div>
        <div id="stat-approved" class="text-3xl font-extrabold text-emerald-400 mt-2">--</div>
        <div class="text-[11px] text-emerald-500/80 mt-1">Valid 19% MwSt & DE-IBAN</div>
      </div>

      <div class="bg-slate-900 border border-slate-800 rounded-2xl p-5 shadow-sm">
        <div class="text-xs font-medium text-slate-400">AML Alerts Flagged (≥ €10k)</div>
        <div id="stat-aml" class="text-3xl font-extrabold text-amber-400 mt-2">--</div>
        <div class="text-[11px] text-amber-500/80 mt-1">Published to Amazon SNS</div>
      </div>

      <div class="bg-slate-900 border border-slate-800 rounded-2xl p-5 shadow-sm">
        <div class="text-xs font-medium text-slate-400">Dead-Letter Queue (DLQ)</div>
        <div id="stat-dlq" class="text-3xl font-extrabold text-rose-400 mt-2">--</div>
        <div class="text-[11px] text-rose-500/80 mt-1">Poison-pill messages quarantined</div>
      </div>
    </div>

    <!-- Interactive Simulation Playground -->
    <div class="bg-slate-900/60 border border-slate-800 rounded-2xl p-6 backdrop-blur">
      <div class="mb-5">
        <h2 class="text-base font-bold text-white flex items-center gap-2">
          <span>🧪</span> Live Architecture Simulation Playground
        </h2>
        <p class="text-xs text-slate-400">Click a scenario button to upload an invoice to S3, publish to SQS, and run the worker through least-privilege IAM and KMS encryption.</p>
      </div>

      <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
        <!-- Scenario 1 -->
        <button onclick="triggerSimulation('standard')" class="text-left bg-slate-800/80 hover:bg-slate-800 border border-slate-700/80 hover:border-emerald-500/50 rounded-xl p-4 transition group">
          <div class="flex items-center justify-between mb-2">
            <span class="text-xs font-semibold px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">Scenario 1</span>
            <span class="text-xs text-slate-500 group-hover:text-emerald-400 transition">Execute &rarr;</span>
          </div>
          <div class="text-sm font-semibold text-white">Standard Invoice (€1,190)</div>
          <p class="text-xs text-slate-400 mt-1">Valid DE-IBAN + correct 19% VAT. Result: Stamped <b class="text-emerald-400">APPROVED</b> in DynamoDB.</p>
        </button>

        <!-- Scenario 2 -->
        <button onclick="triggerSimulation('aml')" class="text-left bg-slate-800/80 hover:bg-slate-800 border border-slate-700/80 hover:border-amber-500/50 rounded-xl p-4 transition group">
          <div class="flex items-center justify-between mb-2">
            <span class="text-xs font-semibold px-2 py-0.5 rounded bg-amber-500/10 text-amber-400 border border-amber-500/20">Scenario 2</span>
            <span class="text-xs text-slate-500 group-hover:text-amber-400 transition">Execute &rarr;</span>
          </div>
          <div class="text-sm font-semibold text-white">AML High-Value (€23,800)</div>
          <p class="text-xs text-slate-400 mt-1">Exceeds German GwG €10k threshold. Result: Stamped <b class="text-amber-400">FLAGGED_AML</b> + SNS Alert.</p>
        </button>

        <!-- Scenario 3 -->
        <button onclick="triggerSimulation('poison')" class="text-left bg-slate-800/80 hover:bg-slate-800 border border-slate-700/80 hover:border-rose-500/50 rounded-xl p-4 transition group">
          <div class="flex items-center justify-between mb-2">
            <span class="text-xs font-semibold px-2 py-0.5 rounded bg-rose-500/10 text-rose-400 border border-rose-500/20">Scenario 3</span>
            <span class="text-xs text-slate-500 group-hover:text-rose-400 transition">Execute &rarr;</span>
          </div>
          <div class="text-sm font-semibold text-white">Poison-Pill Chaos Test</div>
          <p class="text-xs text-slate-400 mt-1">Invalid IBAN and negative VAT. Fails 3 retries and routes to <b class="text-rose-400">Dead-Letter Queue</b>.</p>
        </button>
      </div>

      <!-- Action Toast / Response -->
      <div id="sim-toast" class="hidden mt-4 p-3 rounded-lg bg-slate-800 border border-slate-700 text-xs font-mono text-slate-300"></div>
    </div>

    <!-- Live Compliance Audit Ledger Table -->
    <div class="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden shadow-sm">
      <div class="px-6 py-4 border-b border-slate-800 flex justify-between items-center">
        <div>
          <h2 class="text-base font-bold text-white flex items-center gap-2">
            <span>📋</span> Live DynamoDB Compliance Audit Ledger
          </h2>
          <p class="text-xs text-slate-400">Immutable records encrypted with Customer Managed KMS Key (CMK)</p>
        </div>
        <span class="text-xs text-slate-500 font-mono" id="table-record-count">0 records</span>
      </div>

      <div class="overflow-x-auto">
        <table class="w-full text-left text-xs">
          <thead class="bg-slate-950/50 text-slate-400 uppercase tracking-wider text-[10px] border-b border-slate-800 font-semibold">
            <tr>
              <th class="px-6 py-3">Invoice ID</th>
              <th class="px-6 py-3">Status</th>
              <th class="px-6 py-3">Gross Amount</th>
              <th class="px-6 py-3">19% VAT</th>
              <th class="px-6 py-3">Sender IBAN</th>
              <th class="px-6 py-3">Timestamp (UTC)</th>
            </tr>
          </thead>
          <tbody id="audit-table-body" class="divide-y divide-slate-800/60 font-mono text-slate-300">
            <tr>
              <td colspan="6" class="px-6 py-8 text-center text-slate-500 font-sans">No audit records found. Click a scenario button above to process invoices!</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

  </main>

  <script>
    async function refreshData() {
      try {
        const res = await fetch('/api/status');
        const data = await res.json();
        
        // Update Emulator Pill
        const pill = document.getElementById('emulator-pill');
        if (data.emulator_healthy) {
          pill.className = "flex items-center gap-2 text-xs font-semibold px-3 py-1.5 rounded-full bg-emerald-500/10 border border-emerald-500/30 text-emerald-400";
          pill.innerHTML = `<span class="h-2 w-2 rounded-full bg-emerald-400"></span> AWS Emulator Online (:9297)`;
        } else {
          pill.className = "flex items-center gap-2 text-xs font-semibold px-3 py-1.5 rounded-full bg-rose-500/10 border border-rose-500/30 text-rose-400";
          pill.innerHTML = `<span class="h-2 w-2 rounded-full bg-rose-400"></span> AWS Emulator Offline`;
        }

        // Stats
        document.getElementById('stat-total').innerText = data.total_audited;
        document.getElementById('stat-approved').innerText = data.approved_count;
        document.getElementById('stat-aml').innerText = data.aml_count;
        document.getElementById('stat-dlq').innerText = data.dlq_count;
        document.getElementById('table-record-count').innerText = `${data.total_audited} total records`;

        // Table
        const tbody = document.getElementById('audit-table-body');
        if (data.records && data.records.length > 0) {
          tbody.innerHTML = data.records.map(r => {
            const isAml = r.compliance_status === 'FLAGGED_AML';
            const badge = isAml
              ? `<span class="px-2 py-0.5 rounded text-[10px] font-bold bg-amber-500/20 text-amber-400 border border-amber-500/30">FLAGGED_AML</span>`
              : `<span class="px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">APPROVED</span>`;
            return `
              <tr class="hover:bg-slate-800/40 transition">
                <td class="px-6 py-3.5 font-bold text-white">${r.invoice_id}</td>
                <td class="px-6 py-3.5">${badge}</td>
                <td class="px-6 py-3.5 font-bold ${isAml ? 'text-amber-400' : 'text-slate-100'}">${parseFloat(r.gross_amount).toLocaleString('de-DE', {minimumFractionDigits: 2})} EUR</td>
                <td class="px-6 py-3.5 text-slate-400">${parseFloat(r.vat_amount).toLocaleString('de-DE', {minimumFractionDigits: 2})} EUR</td>
                <td class="px-6 py-3.5 text-slate-400">${r.sender_iban}</td>
                <td class="px-6 py-3.5 text-slate-500 text-[11px]">${r.processed_at ? r.processed_at.substring(0, 19).replace('T', ' ') : '--'}</td>
              </tr>
            `;
          }).join('');
        }
      } catch (err) {
        console.error("Failed to fetch dashboard status", err);
      }
    }

    async function triggerSimulation(type) {
      const toast = document.getElementById('sim-toast');
      toast.classList.remove('hidden');
      toast.innerText = `Executing scenario: ${type}... sending invoice through S3 -> SQS -> Worker...`;
      
      try {
        const res = await fetch(`/api/simulate/${type}`, { method: 'POST' });
        const result = await res.json();
        toast.innerText = `Result for ${result.invoice_id}: ${JSON.stringify(result.processor_result)}`;
        await refreshData();
      } catch (err) {
        toast.innerText = `Error: ${err.message}`;
      }
    }

    // Auto-refresh every 3 seconds
    refreshData();
    setInterval(refreshData, 3000);
  </script>
</body>
</html>
"""
