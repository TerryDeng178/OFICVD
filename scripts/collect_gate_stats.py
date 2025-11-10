# -*- coding: utf-8 -*-
"""收集Gate统计信息并生成gate_stats.jsonl"""
import argparse
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any
from collections import defaultdict, Counter
import glob

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def load_jsonl(file_path: Path) -> List[Dict[str, Any]]:
    """加载JSONL文件"""
    records = []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
    except Exception as e:
        logger.error(f"Error loading {file_path}: {e}")
    return records


def collect_gate_stats_from_signals(signals: List[Dict[str, Any]]) -> Dict[str, Any]:
    """从信号记录中收集gate统计"""
    gate_stats = {
        "total_signals": len(signals),
        "confirmed": 0,
        "blocked": 0,
        "gate_reasons": defaultdict(int),
        "top_reasons": []
    }
    
    for signal in signals:
        gate_reason = signal.get("gate_reason") or signal.get("guard_reason")
        gating = signal.get("gating", False) or signal.get("gating_blocked", False)
        confirm = signal.get("confirm", False)
        
        if confirm:
            gate_stats["confirmed"] += 1
        else:
            gate_stats["blocked"] += 1
        
        if gate_reason:
            # gate_reason可能是逗号分隔的多个原因
            reasons = [r.strip() for r in gate_reason.split(",") if r.strip()]
            for reason in reasons:
                gate_stats["gate_reasons"][reason] += 1
    
    # 计算top原因
    sorted_reasons = sorted(
        gate_stats["gate_reasons"].items(),
        key=lambda x: x[1],
        reverse=True
    )
    gate_stats["top_reasons"] = [
        {"reason": reason, "count": count, "percentage": count / gate_stats["blocked"] * 100 if gate_stats["blocked"] > 0 else 0}
        for reason, count in sorted_reasons[:10]
    ]
    
    # 转换为普通dict以便JSON序列化
    gate_stats["gate_reasons"] = dict(gate_stats["gate_reasons"])
    
    return gate_stats


def collect_gate_stats_from_breakdown(breakdown_file: Path) -> Dict[str, Any]:
    """从gate_reason_breakdown.json收集统计"""
    try:
        with open(breakdown_file, "r", encoding="utf-8") as f:
            breakdown = json.load(f)
        
        total = sum(breakdown.values())
        sorted_reasons = sorted(
            breakdown.items(),
            key=lambda x: x[1],
            reverse=True
        )
        
        return {
            "source": "gate_reason_breakdown.json",
            "total": total,
            "breakdown": breakdown,
            "top_reasons": [
                {"reason": reason, "count": count, "percentage": count / total * 100 if total > 0 else 0}
                for reason, count in sorted_reasons[:10]
            ]
        }
    except Exception as e:
        logger.error(f"Error loading breakdown file {breakdown_file}: {e}")
        return {}


def generate_gate_stats_jsonl(
    input_dir: Path,
    output_file: Path,
    source: str = "signals"
) -> None:
    """生成gate_stats.jsonl"""
    stats_records = []
    
    if source == "signals":
        # 从signals JSONL文件收集
        signal_files = list(input_dir.glob("**/signals_*.jsonl"))
        if not signal_files:
            logger.warning(f"No signal files found in {input_dir}")
            return
        
        for signal_file in signal_files:
            logger.info(f"Processing {signal_file}")
            signals = load_jsonl(signal_file)
            
            if signals:
                stats = collect_gate_stats_from_signals(signals)
                stats["source_file"] = str(signal_file)
                stats["timestamp"] = signal_file.stat().st_mtime
                stats_records.append(stats)
    
    elif source == "breakdown":
        # 从gate_reason_breakdown.json收集
        breakdown_files = list(input_dir.glob("**/gate_reason_breakdown.json"))
        
        for breakdown_file in breakdown_files:
            logger.info(f"Processing {breakdown_file}")
            stats = collect_gate_stats_from_breakdown(breakdown_file)
            if stats:
                stats["source_file"] = str(breakdown_file)
                stats["timestamp"] = breakdown_file.stat().st_mtime
                stats_records.append(stats)
    
    elif source == "both":
        # 同时从signals和breakdown收集
        signal_files = list(input_dir.glob("**/signals_*.jsonl"))
        breakdown_files = list(input_dir.glob("**/gate_reason_breakdown.json"))
        
        for signal_file in signal_files:
            logger.info(f"Processing signals from {signal_file}")
            signals = load_jsonl(signal_file)
            if signals:
                stats = collect_gate_stats_from_signals(signals)
                stats["source_file"] = str(signal_file)
                stats["source_type"] = "signals"
                stats["timestamp"] = signal_file.stat().st_mtime
                stats_records.append(stats)
        
        for breakdown_file in breakdown_files:
            logger.info(f"Processing breakdown from {breakdown_file}")
            stats = collect_gate_stats_from_breakdown(breakdown_file)
            if stats:
                stats["source_file"] = str(breakdown_file)
                stats["source_type"] = "breakdown"
                stats["timestamp"] = breakdown_file.stat().st_mtime
                stats_records.append(stats)
    
    # 写入JSONL
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        for record in stats_records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    
    logger.info(f"Generated {len(stats_records)} gate stats records to {output_file}")


def generate_summary_report(
    gate_stats_file: Path,
    output_report: Path
) -> None:
    """生成汇总报告"""
    stats_records = []
    with open(gate_stats_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                stats_records.append(json.loads(line))
    
    if not stats_records:
        logger.warning("No stats records found")
        return
    
    # 汇总所有记录
    total_confirmed = sum(r.get("confirmed", 0) for r in stats_records)
    total_blocked = sum(r.get("blocked", 0) for r in stats_records)
    total_signals = sum(r.get("total_signals", 0) for r in stats_records)
    
    # 合并所有gate_reasons
    all_reasons = defaultdict(int)
    for record in stats_records:
        reasons = record.get("gate_reasons", {}) or record.get("breakdown", {})
        for reason, count in reasons.items():
            all_reasons[reason] += count
    
    # P1-2修复: 如果total_blocked为0但all_reasons有数据，使用all_reasons的总和作为total_blocked
    if total_blocked == 0 and all_reasons:
        total_blocked = sum(all_reasons.values())
    
    sorted_all_reasons = sorted(
        all_reasons.items(),
        key=lambda x: x[1],
        reverse=True
    )
    
    # 生成Markdown报告
    md_content = f"""# Gate统计汇总报告

**生成时间**: {Path(__file__).stat().st_mtime}  
**数据源**: {gate_stats_file}  
**记录数**: {len(stats_records)}

## 总体统计

- **总信号数**: {total_signals}
- **确认信号**: {total_confirmed} ({(total_confirmed/total_signals*100) if total_signals > 0 else 0.0:.2f}%)
- **被阻止信号**: {total_blocked} ({(total_blocked/total_signals*100) if total_signals > 0 else 0.0:.2f}%)

## Gate原因Top-10

"""
    
    for i, (reason, count) in enumerate(sorted_all_reasons[:10], 1):
        percentage = count / total_blocked * 100 if total_blocked > 0 else 0
        md_content += f"{i}. **{reason}**: {count}次 ({percentage:.2f}%)\n"
    
    md_content += "\n## 主因门检查\n\n"
    
    if sorted_all_reasons:
        top1_reason = sorted_all_reasons[0][0]
        top1_count = sorted_all_reasons[0][1]
        top1_pct = top1_count / total_blocked * 100 if total_blocked > 0 else 0
        
        md_content += f"- **Top-1原因**: {top1_reason}\n"
        md_content += f"- **Top-1占比**: {top1_pct:.2f}%\n"
        
        # P1-2修复: 自动判定Top-1<60%（DoD自动化）
        threshold = 60.0
        passed = top1_pct < threshold
        status_icon = "✅" if passed else "❌"
        status_text = "通过" if passed else "未通过"
        
        md_content += f"\n{status_icon} **状态**: {status_text} (Top-1占比 {top1_pct:.2f}% {'<' if passed else '≥'} {threshold}%)\n"
        
        if not passed:
            md_content += f"\n⚠️ **警告**: Top-1原因占比 ≥ {threshold}%，存在主因门压制问题\n"
        else:
            md_content += f"\n✅ **通过**: Top-1原因占比 < {threshold}%，无主因门压制\n"
    
    md_content += "\n## 详细记录\n\n"
    
    for i, record in enumerate(stats_records, 1):
        md_content += f"### 记录 {i}\n\n"
        md_content += f"- **来源**: {record.get('source_file', 'N/A')}\n"
        md_content += f"- **总信号**: {record.get('total_signals', record.get('total', 0))}\n"
        md_content += f"- **确认**: {record.get('confirmed', 0)}\n"
        md_content += f"- **阻止**: {record.get('blocked', 0)}\n"
        
        top_reasons = record.get("top_reasons", [])
        if top_reasons:
            md_content += "\n**Top原因**:\n"
            for tr in top_reasons[:5]:
                md_content += f"- {tr['reason']}: {tr['count']}次 ({tr['percentage']:.2f}%)\n"
        md_content += "\n"
    
    output_report.parent.mkdir(parents=True, exist_ok=True)
    with open(output_report, "w", encoding="utf-8") as f:
        f.write(md_content)
    
    logger.info(f"Summary report saved to {output_report}")


def main():
    parser = argparse.ArgumentParser(description="收集Gate统计信息")
    parser.add_argument("--in", dest="input_dir", type=str, default="./runtime", help="输入目录（搜索signals或gate_reason_breakdown.json）")
    parser.add_argument("--out", dest="output_file", type=str, default="./runtime/artifacts/gate_stats.jsonl", help="输出gate_stats.jsonl路径")
    parser.add_argument("--source", type=str, choices=["signals", "breakdown", "both"], default="both", help="数据源类型")
    parser.add_argument("--report", type=str, default="./runtime/reports/report_consistency.md", help="输出汇总报告路径")
    
    args = parser.parse_args()
    
    input_dir = Path(args.input_dir)
    output_file = Path(args.output_file)
    
    if not input_dir.exists():
        logger.error(f"Input directory not found: {input_dir}")
        return 1
    
    generate_gate_stats_jsonl(input_dir, output_file, source=args.source)
    
    if args.report:
        generate_summary_report(output_file, Path(args.report))
    
    return 0


if __name__ == "__main__":
    exit(main())

