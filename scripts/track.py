#!/usr/bin/env python3
"""Local evidence ledger. Does not fetch pages or claim to verify source truth."""
import argparse
from collections import Counter
from datetime import date, datetime, time, timezone
import fcntl
import hashlib
import json
from pathlib import Path
import tempfile
import uuid
from zoneinfo import ZoneInfo

TZ = ZoneInfo('Asia/Shanghai')
LABELS = {
    'confirmed_bookable': '已核验可预订', 'open_by_terms': '规则期内候选',
    'needs_verification': '待核实', 'expired': '已结束',
    'not_started': '未开始', 'unavailable': '当前不可售', 'ineligible': '不适用',
}


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write(path, data):
    path = Path(path)
    with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent,
                                     delete=False) as out:
        json.dump(data, out, ensure_ascii=False, indent=2, allow_nan=False)
        out.write('\n')
        temp = Path(out.name)
    temp.replace(path)


def timestamp(value):
    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if dt.tzinfo is None:
        raise ValueError('时间戳必须包含时区')
    return dt


def boundary(value, end=False):
    if not value:
        return None
    if len(value) == 10:
        return datetime.combine(date.fromisoformat(value), time.max if end else time.min, TZ)
    return timestamp(value)


def classify(offer, sources, now):
    source = sources.get(offer.get('source_id'), {})
    if source.get('status') != 'ok':
        return 'needs_verification', '本轮规则来源不可用'
    if source.get('kind') == 'search':
        return 'needs_verification', '搜索摘要只用于发现，需读取活动原文'
    if offer.get('conflict'):
        return 'needs_verification', '规则存在未解决的冲突'
    if offer.get('eligibility') == 'excluded':
        return 'ineligible', '不符合本次行程或个人资格'
    known_year = offer.get('booking_year_verified') is True
    start = boundary(offer.get('booking_start')) if known_year else None
    end = boundary(offer.get('booking_end'), end=True) if known_year else None
    if start and end and start > end:
        raise ValueError('预订起始晚于截止日期')
    if end and now > end:
        return 'expired', '预订/购买窗口已结束，入住或核销期不延长购买期'
    if start and now < start:
        return 'not_started', '预订/购买窗口尚未开始'
    if offer.get('availability') == 'unavailable':
        merchant = sources.get(offer.get('merchant_source_id'), {})
        if merchant.get('kind') == 'merchant' and merchant.get('status') == 'ok':
            return 'unavailable', '本轮销售页显示当前不可售'
        return 'needs_verification', '不可售判断缺少本轮销售页证据'
    is_open = known_year and (end is not None or offer.get('booking_open_ended') is True)
    if not is_open:
        return 'needs_verification', '预订年份/购买截止或持续开放依据未确认'
    merchant = sources.get(offer.get('merchant_source_id'), {})
    price = offer.get('price', {}).get('cash')
    if (offer.get('availability') == 'available'
            and offer.get('itinerary_match') is True
            and offer.get('eligibility') == 'matched'
            and offer.get('terms_checked') is True
            and not offer.get('missing')
            and merchant.get('kind') == 'merchant' and merchant.get('status') == 'ok'
            and isinstance(price, (int, float)) and not isinstance(price, bool) and price >= 0):
        return 'confirmed_bookable', '本轮规则、销售页、具体项目和资格已匹配'
    return 'open_by_terms', '当前在规则预订期内，库存/价格/资格仍需补核'


def validate(data, context, run, now):
    if data.get('run_id') != context['run_id']:
        raise ValueError('run_id 不匹配')
    if data.get('coverage') not in ('partial', 'complete') or not data.get('coverage_note'):
        raise ValueError('填写 coverage 和实际 coverage_note')
    sources = {}
    for s in data.get('sources', []):
        if not s.get('id') or s['id'] in sources or not s.get('url', '').startswith(('http://', 'https://')):
            raise ValueError('来源必须有唯一 id 和真实 URL')
        if s.get('kind') not in ('document', 'merchant', 'search') or s.get('status') not in ('ok', 'blocked'):
            raise ValueError('来源 kind/status 无效')
        if s['status'] == 'ok':
            fetched = timestamp(s['fetched_at'])
            if (fetched < timestamp(context['started_at']) or fetched > now
                    or fetched.astimezone(TZ).date() != now.astimezone(TZ).date()):
                raise ValueError('拒绝旧缓存或未来采集时间；需本轮且当日新读取证据')
            if not s.get('evidence'):
                raise ValueError('ok 来源必须关联证据')
            hashes = {}
            for item in s['evidence']:
                path = (run / item).resolve()
                if not path.is_relative_to((run / 'evidence').resolve()) or not path.is_file() or path.stat().st_size == 0:
                    raise ValueError('证据必须为本轮 evidence/ 内的非空文件')
                hashes[item] = hashlib.sha256(path.read_bytes()).hexdigest()
            s['evidence_sha256'] = hashes
        elif not s.get('note'):
            raise ValueError('blocked 来源必须说明原因')
        sources[s['id']] = s
    ids = set()
    for o in data.get('offers', []):
        if not o.get('id') or o['id'] in ids or not o.get('title') or o.get('source_id') not in sources:
            raise ValueError('项目必须有唯一 id、标题及本轮来源')
        if not o.get('url', '').startswith(('http://', 'https://')):
            raise ValueError('项目需真实 URL')
        if o.get('availability', 'unknown') not in ('available', 'unavailable', 'unknown'):
            raise ValueError('availability 无效')
        if o.get('eligibility', 'unknown') not in ('matched', 'excluded', 'unknown'):
            raise ValueError('eligibility 无效')
        if o.get('merchant_source_id') and o['merchant_source_id'] not in sources:
            raise ValueError('merchant_source_id 不存在')
        for field in ('booking_year_verified', 'booking_open_ended', 'itinerary_match', 'terms_checked', 'conflict'):
            if field in o and not isinstance(o[field], bool):
                raise ValueError(f'{field} 必须为布尔值')
        if not isinstance(o.get('missing', []), list):
            raise ValueError('missing 必须为数组')
        for field in ('booking_start', 'booking_end'):
            boundary(o.get(field), end=(field == 'booking_end'))
        ids.add(o['id'])
    if not sources and data['coverage'] == 'complete':
        raise ValueError('无来源不能声明完成覆盖')
    if data['coverage'] == 'complete' and any(s['status'] == 'blocked' for s in sources.values()):
        raise ValueError('来源阻断时 coverage 应为 partial')
    return sources


def comparable(offer):
    excluded = {'reason', 'source_id', 'merchant_source_id', 'fetched_at', 'evidence', 'last_observed_run_id'}
    return {k: v for k, v in offer.items() if k not in excluded}


def changes(previous, current, run_id):
    old = {o['id']: o for o in previous.get('offers', [])}
    for o in previous.get('not_rechecked', []):
        old.setdefault(o['id'], o)
    fresh = {o['id']: o for o in current}
    delta = {'added': [], 'changed': [], 'unchanged': [], 'not_rechecked': []}
    for key, offer in fresh.items():
        kind = 'added' if key not in old else ('changed' if comparable(offer) != comparable(old[key]) else 'unchanged')
        delta[kind].append(key)
    missing = []
    for key, offer in old.items():
        if key not in fresh:
            stale = dict(offer)
            stale.setdefault('last_observed_run_id', previous.get('run_id'))
            missing.append(stale)
            delta['not_rechecked'].append(key)
    for offer in current:
        offer['last_observed_run_id'] = run_id
    return delta, missing


def start(state):
    state = Path(state).expanduser().resolve()
    (state / 'runs').mkdir(parents=True, exist_ok=True)
    now = datetime.now(TZ)
    run_id = now.strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex[:8]
    run = state / 'runs' / run_id
    (run / 'evidence').mkdir(parents=True)
    prior = read(state / 'latest.json') if (state / 'latest.json').exists() else {}
    context = {'run_id': run_id, 'started_at': now.isoformat(), 'timezone': str(TZ),
               'previous_run_id': prior.get('run_id')}
    write(run / 'context.json', context)
    write(run / 'observations.json', {'run_id': run_id, 'coverage': 'partial',
          'coverage_note': '', 'sources': [], 'offers': []})
    return {'run_dir': str(run), **context}


def finish(run, input_path):
    run = Path(run).resolve()
    context = read(run / 'context.json')
    if (run / 'result.json').exists():
        raise ValueError('本轮已完成；查看 result.json，重新采集需 start 新一轮')
    state = run.parent.parent
    now = datetime.now(TZ)
    data = read(input_path)
    sources = validate(data, context, run, now)
    offers = data.get('offers', [])
    for offer in offers:
        offer['status'], offer['reason'] = classify(offer, sources, now)
    with (state / '.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        previous = read(state / 'latest.json') if (state / 'latest.json').exists() else {}
        if previous.get('run_id') != context.get('previous_run_id'):
            raise ValueError('另一轮已更新状态；保留本轮证据，另启一轮重新读取，避免覆盖新结果')
        delta, missing = changes(previous, offers, context['run_id'])
        result = {**context, **data, 'checked_at': now.isoformat(), 'offers': offers,
                  'changes': delta, 'not_rechecked': missing,
                  'counts': dict(Counter(o['status'] for o in offers))}
        lines = ['# 酒店优惠本轮核验', '', f"检查时间：{result['checked_at']}", '',
                 f"覆盖：{data['coverage']}；{data['coverage_note']}", '',
                 f"已核验可预订 {result['counts'].get('confirmed_bookable', 0)} 项；规则期内候选 {result['counts'].get('open_by_terms', 0)} 项。", '']
        for offer in offers:
            lines.extend([f"## {offer['title']}", '', f"{LABELS[offer['status']]}：{offer['reason']}", '',
                          f"预订期原文：{offer.get('booking_raw') or '未明确'}", '',
                          f"实付及估值：{json.dumps(offer.get('price', {}), ensure_ascii=False)}", '',
                          f"待核实：{'；'.join(offer.get('missing', [])) or '无记录缺项'}", '',
                          f"来源：{offer['url']}", ''])
        if missing:
            lines.extend(['## 本轮未复核', '', *[f"- {o['title']}（旧记录，不代表当前有效或已下架）" for o in missing], ''])
        (run / 'report.md').write_text('\n'.join(lines), encoding='utf-8')
        write(run / 'result.json', result)
        write(state / 'latest.json', result)
    return {'run_dir': str(run), 'counts': result['counts'], 'changes': delta}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    a = sub.add_parser('start')
    a.add_argument('--state-dir', required=True)
    b = sub.add_parser('finish')
    b.add_argument('--run-dir', required=True)
    b.add_argument('--input', required=True)
    args = parser.parse_args()
    try:
        result = start(args.state_dir) if args.command == 'start' else finish(args.run_dir, args.input)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        parser.exit(2, f'错误：{exc}\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
