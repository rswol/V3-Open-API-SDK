import asyncio
import websockets
import json
import requests
import dateutil.parser as dp
import hmac
import base64
import zlib
import logging
import datetime

log_format = '%(asctime)s - %(levelname)s - %(message)s'
logging.basicConfig(filename='mylog-ws.json', filemode='w', format=log_format, level=logging.INFO)


def get_timestamp():
    now = datetime.datetime.now()
    t = now.isoformat("T", "milliseconds")
    return t + "Z"


def get_server_time():
    url = "https://www.okcoin.com/api/general/v3/time"
    response = requests.get(url)
    if response.status_code == 200:
        return response.json()['iso']
    else:
        return ""


def server_timestamp():
    server_time = get_server_time()
    parsed_t = dp.parse(server_time)
    timestamp = parsed_t.timestamp()
    return timestamp


def login_params(timestamp, api_key, passphrase, secret_key):
    message = timestamp + 'GET' + '/users/self/verify'

    mac = hmac.new(bytes(secret_key, encoding='utf8'), bytes(message, encoding='utf-8'), digestmod='sha256')
    d = mac.digest()
    sign = base64.b64encode(d)

    login_param = {"op": "login", "args": [api_key, passphrase, timestamp, sign.decode("utf-8")]}
    login_str = json.dumps(login_param)
    return login_str


def inflate(data):
    decompress = zlib.decompressobj(
            -zlib.MAX_WBITS  # see above
    )
    inflated = decompress.decompress(data)
    inflated += decompress.flush()
    return inflated


def partial(res, timestamp):
    data_obj = res['data'][0]
    bids = data_obj['bids']
    asks = data_obj['asks']
    instrument_id = data_obj['instrument_id']
    print(timestamp + '全量数据bids为：' + str(bids))
    logging.info('partial bids:' + str(bids))
    print('档数为：' + str(len(bids)))
    print(timestamp + '全量数据asks为：' + str(asks))
    logging.info('partial asks:' + str(asks))
    print('档数为：' + str(len(asks)))
    return bids, asks, instrument_id


def update_bids(res, bids_p, timestamp):
    # 获取增量bids数据
    bids_u = res['data'][0]['bids']
    print(timestamp + '增量数据bids为：' + str(bids_u))
    print('档数为：' + str(len(bids_u)))
    # bids合并
    for i in bids_u:
        bid_price = i[0]
        for j in bids_p:
            if bid_price == j[0]:
                if i[1] == '0':
                    bids_p.remove(j)
                    break
                else:
                    del j[1]
                    j.insert(1, i[1])
                    break
        else:
            if i[1] != "0":
                bids_p.append(i)
    else:
        bids_p.sort(key=lambda price: sort_num(price[0]), reverse=True)
        print(timestamp + '合并后的bids为：' + str(bids_p) + '，档数为：' + str(len(bids_p)))
        logging.info('combine bids:' + str(bids_p))
    return bids_p


def update_asks(res, asks_p, timestamp):
    # 获取增量asks数据
    asks_u = res['data'][0]['asks']
    print(timestamp + '增量数据asks为：' + str(asks_u))
    print('档数为：' + str(len(asks_u)))
    # asks合并
    for i in asks_u:
        ask_price = i[0]
        for j in asks_p:
            if ask_price == j[0]:
                if i[1] == '0':
                    asks_p.remove(j)
                    break
                else:
                    del j[1]
                    j.insert(1, i[1])
                    break
        else:
            if i[1] != "0":
                asks_p.append(i)
    else:
        asks_p.sort(key=lambda price: sort_num(price[0]))
        print(timestamp + '合并后的asks为：' + str(asks_p) + '，档数为：' + str(len(asks_p)))
        logging.info('combine asks:' + str(asks_p))
    return asks_p


def sort_num(n):
    if n.isdigit():
        return int(n)
    else:
        return float(n)


def check(bids, asks):
    # 获取bid档str
    bids_l = []
    bid_l = []
    count_bid = 1
    while count_bid <= 25:
        if count_bid > len(bids):
            break
        bids_l.append(bids[count_bid-1])
        count_bid += 1
    for j in bids_l:
        str_bid = ':'.join(j[0 : 2])
        bid_l.append(str_bid)
    # 获取ask档str
    asks_l = []
    ask_l = []
    count_ask = 1
    while count_ask <= 25:
        if count_ask > len(asks):
            break
        asks_l.append(asks[count_ask-1])
        count_ask += 1
    for k in asks_l:
        str_ask = ':'.join(k[0 : 2])
        ask_l.append(str_ask)
    # 拼接str
    num = ''
    if len(bid_l) == len(ask_l):
        for m in range(len(bid_l)):
            num += bid_l[m] + ':' + ask_l[m] + ':'
    elif len(bid_l) > len(ask_l):
        # bid档比ask档多
        for n in range(len(ask_l)):
            num += bid_l[n] + ':' + ask_l[n] + ':'
        for l in range(len(ask_l), len(bid_l)):
            num += bid_l[l] + ':'
    elif len(bid_l) < len(ask_l):
        # ask档比bid档多
        for n in range(len(bid_l)):
            num += bid_l[n] + ':' + ask_l[n] + ':'
        for l in range(len(bid_l), len(ask_l)):
            num += ask_l[l] + ':'

    new_num = num[:-1]
    int_checksum = zlib.crc32(new_num.encode())
    fina = change(int_checksum)
    return fina


def change(num_old):
    num = pow(2, 31) - 1
    if num_old > num:
        out = num_old - num * 2 - 2
    else:
        out = num_old
    return out


# subscribe channels un_need login
async def subscribe_without_login(url, channels):
    l = []
    while True:
        try:
            async with websockets.connect(url) as ws:
                sub_param = {"op": "subscribe", "args": channels}
                sub_str = json.dumps(sub_param)
                await ws.send(sub_str)
                logging.info(f"send: {sub_str}")

                while True:
                    try:
                        res_b = await asyncio.wait_for(ws.recv(), timeout=25)
                    except (asyncio.TimeoutError, websockets.exceptions.ConnectionClosed) as e:
                        # logging.error(e)
                        try:
                            await ws.send('ping')
                            res_b = await ws.recv()
                            timestamp = get_timestamp()
                            res = inflate(res_b).decode('utf-8')
                            print(timestamp + res)
                            logging.info(res)
                            continue
                        except Exception as e:
                            timestamp = get_timestamp()
                            print(timestamp + "连接关闭，正在重连……")
                            logging.error(e)
                            break

                    timestamp = get_timestamp()
                    res = inflate(res_b).decode('utf-8')
                    print(timestamp + res)
                    logging.info(f"recv: {res}")

                    res = eval(res)
                    if 'event' in res:
                        continue
                    for i in res:
                        if 'depth' in res[i] and 'depth5' not in res[i]:
                            # 订阅频道是深度频道
                            if res['action'] == 'partial':
                                for m in l:
                                    if res['data'][0]['instrument_id'] == m['instrument_id']:
                                        l.remove(m)
                                # 获取首次全量深度数据
                                bids_p, asks_p, instrument_id = partial(res, timestamp)
                                d = {}
                                d['instrument_id'] = instrument_id
                                d['bids_p'] = bids_p
                                d['asks_p'] = asks_p
                                l.append(d)

                                # 校验checksum
                                checksum = res['data'][0]['checksum']
                                print(timestamp + '推送数据的checksum为：' + str(checksum))
                                logging.info('get checksum:' + str(checksum))
                                check_num = check(bids_p, asks_p)
                                print(timestamp + '校验后的checksum为：' + str(check_num))
                                logging.info('calculate checksum:' + str(check_num))
                                if check_num == checksum:
                                    print("校验结果为：True")
                                    logging.info('checksum: True')
                                else:
                                    print("校验结果为：False，正在重新订阅……")
                                    logging.error('checksum: False')

                                    # 取消订阅
                                    await unsubscribe_without_login(url, channels, timestamp)
                                    # 发送订阅
                                    async with websockets.connect(url) as ws:
                                        sub_param = {"op": "subscribe", "args": channels}
                                        sub_str = json.dumps(sub_param)
                                        await ws.send(sub_str)
                                        timestamp = get_timestamp()
                                        print(timestamp + f"send: {sub_str}")
                                        logging.info(f"send: {sub_str}")

                            elif res['action'] == 'update':
                                for j in l:
                                    if res['data'][0]['instrument_id'] == j['instrument_id']:
                                        # 获取全量数据
                                        bids_p = j['bids_p']
                                        asks_p = j['asks_p']
                                        # 获取合并后数据
                                        bids_p = update_bids(res, bids_p, timestamp)
                                        asks_p = update_asks(res, asks_p, timestamp)

                                        # 校验checksum
                                        checksum = res['data'][0]['checksum']
                                        print(timestamp + '推送数据的checksum为：' + str(checksum))
                                        logging.info('get checksum:' + str(checksum))
                                        check_num = check(bids_p, asks_p)
                                        print(timestamp + '校验后的checksum为：' + str(check_num))
                                        logging.info('calculate checksum:' + str(check_num))
                                        if check_num == checksum:
                                            print("校验结果为：True")
                                            logging.info('checksum: True')
                                        else:
                                            print("校验结果为：False，正在重新订阅……")
                                            logging.error('checksum: False')

                                            # 取消订阅
                                            await unsubscribe_without_login(url, channels, timestamp)
                                            # 发送订阅
                                            async with websockets.connect(url) as ws:
                                                sub_param = {"op": "subscribe", "args": channels}
                                                sub_str = json.dumps(sub_param)
                                                await ws.send(sub_str)
                                                timestamp = get_timestamp()
                                                print(timestamp + f"send: {sub_str}")
                                                logging.info(f"send: {sub_str}")
        except Exception as e:
            timestamp = get_timestamp()
            print(timestamp + "连接断开，正在重连……")
            logging.error(e)
            continue


# subscribe channels need login
async def subscribe(url, api_key, passphrase, secret_key, channels):
    while True:
        try:
            async with websockets.connect(url) as ws:
                # login
                timestamp = str(server_timestamp())
                login_str = login_params(timestamp, api_key, passphrase, secret_key)
                await ws.send(login_str)
                # time = get_timestamp()
                # print(time + f"send: {login_str}")
                # logging.info(f"send: {login_str}")
                res_b = await ws.recv()
                res = inflate(res_b).decode('utf-8')
                time = get_timestamp()
                print(time + res)
                logging.info(f"recv: {res}")

                # subscribe
                sub_param = {"op": "subscribe", "args": channels}
                sub_str = json.dumps(sub_param)
                await ws.send(sub_str)
                time = get_timestamp()
                print(time + f"send: {sub_str}")
                logging.info(f"send: {sub_str}")

                while True:
                    try:
                        res_b = await asyncio.wait_for(ws.recv(), timeout=25)
                    except (asyncio.TimeoutError, websockets.exceptions.ConnectionClosed) as e:
                        # logging.error(e)
                        try:
                            await ws.send('ping')
                            res_b = await ws.recv()
                            time = get_timestamp()
                            res = inflate(res_b).decode('utf-8')
                            print(time + res)
                            logging.info(res)
                            continue
                        except Exception as e:
                            time = get_timestamp()
                            print(time + "连接关闭，正在重连……")
                            logging.error(e)
                            break

                    time = get_timestamp()
                    res = inflate(res_b).decode('utf-8')
                    print(time + res)
                    logging.info(f"recv: {res}")

        except Exception as e:
            time = get_timestamp()
            print(time + "连接断开，正在重连……")
            logging.error(e)
            continue


# unsubscribe channels
async def unsubscribe(url, api_key, passphrase, secret_key, channels):
    async with websockets.connect(url) as ws:
        # login
        timestamp = str(server_timestamp())
        login_str = login_params(str(timestamp), api_key, passphrase, secret_key)
        await ws.send(login_str)
        # time = get_timestamp()
        # print(time + f"send: {login_str}")
        # logging.info(f"send: {login_str}")

        res_1 = await ws.recv()
        res = inflate(res_1).decode('utf-8')
        time = get_timestamp()
        print(time + res)
        logging.info(f"recv: {res}")

        # unsubscribe
        sub_param = {"op": "unsubscribe", "args": channels}
        sub_str = json.dumps(sub_param)
        await ws.send(sub_str)
        time = get_timestamp()
        print(time + f"send: {sub_str}")
        logging.info(f"send: {sub_str}")

        res_1 = await ws.recv()
        res = inflate(res_1).decode('utf-8')
        time = get_timestamp()
        print(time + res)
        logging.info(f"recv: {res}")


# unsubscribe channels
async def unsubscribe_without_login(url, channels, timestamp):
    async with websockets.connect(url) as ws:
        # unsubscribe
        sub_param = {"op": "unsubscribe", "args": channels}
        sub_str = json.dumps(sub_param)
        await ws.send(sub_str)
        print(timestamp + f"send: {sub_str}")
        logging.info(f"send: {sub_str}")

        res_1 = await ws.recv()
        res = inflate(res_1).decode('utf-8')
        print(timestamp + f"recv: {res}")
        logging.info(f"recv: {res}")


api_key = ""
secret_key = ""
passphrase = ""

url = 'wss://real.okcoin.com:10442/ws/v3'

# 现货
# Ticker频道
# channels = ["spot/ticker:BTC-USDT"]
# K线频道
# channels = ["spot/candle60s:BTC-USDT"]
# 交易频道
# channels = ["spot/trade:BTC-USDT"]
# 5档深度频道
# channels = ["spot/depth5:BTC-USDT"]
# 深度频道
# channels = ["spot/depth:BTC-USDT"]
# 全量深度频道
# channels = ["spot/depth_l2_tbt:BTC-USDT"]
# 用户币币账户频道
# channels = ["spot/account:BTC"]
# 用户杠杆账户频道
# channels = ["spot/margin_account:BTC-USDT"]
# 用户交易频道
# channels = ["spot/order:BTC-USDT"]
# 用户策略委托频道
# channels = ["spot/order_algo:LTC-USDT"]


loop = asyncio.get_event_loop()

#公共数据 不需要登录（行情，K线，交易数据，资金费率，限价范围，深度数据，标记价格）
loop.run_until_complete(subscribe_without_login(url, channels))

#个人数据 需要登录（用户账户，用户交易，用户持仓）
# loop.run_until_complete(subscribe(url, api_key, passphrase, secret_key, channels))

loop.close()
