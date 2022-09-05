import argparse
import binascii
import json

from rich.console import Console

console = Console()


def parse_ip_layer(ip_layer: dict):
    try:
        return {
                   'ip': ip_layer.get('ip_ip_src'),
                   'host': ip_layer.get('ip_ip_src_host')
               }, {
                   'ip': ip_layer.get('ip_ip_dst'),
                   'host': ip_layer.get('ip_ip_dst_host'),
               }
    except Exception as e:
        return None


def parse_eth_layer(eth_layer: dict):
    return {
               'mac': eth_layer.get('eth_eth_src')
           }, {
               'mac': eth_layer.get('eth_eth_dst'),
           }


def parse_sll_layer(sll_layer: dict):
    return {
               'mac': sll_layer.get('sll_sll_src_eth')
           }, {
               'mac': None,
           }


def parse_single_http2_layer(http2_layer: dict):
    data, headers = None, None
    if 'http2_http2_body_reassembled_data' in http2_layer:
        data = binascii.unhexlify(http2_layer.get('http2_http2_body_reassembled_data').replace(':', ''))
        try:
            data = data.decode('utf-8')
        except Exception:
            data = http2_layer.get('http2_http2_body_reassembled_data')
    elif 'http2_http2_data_data' in http2_layer:
        data = binascii.unhexlify(http2_layer.get('http2_http2_data_data').replace(':', ''))
        try:
            data = data.decode('utf-8')
        except Exception:
            data = http2_layer.get('http2_http2_body_reassembled_data')
    if 'http2_http2_headers' in http2_layer:
        header_name = http2_layer.get('http2_http2_header_name')
        header_value = http2_layer.get('http2_http2_header_value')
        if len(header_name) != len(header_value):
            print('ERROR http2 unmatched header names with values')
            return headers, data
        headers = dict([x for x in zip(header_name, header_value)])
    return headers, data


def parse_http2(layers: dict, layer_names: list):
    to_return = []
    http2_layer = layers.get('http2')
    if type(http2_layer) is list:
        for l in http2_layer:
            headers, data = parse_single_http2_layer(l)
            to_return.append({
                'headers': headers,
                'data': data
            })
    else:
        headers, data = parse_single_http2_layer(http2_layer)
        to_return.append({
            'headers': headers,
            'data': data
        })
    return to_return


def parse_http3(layers: dict, layer_names: list):
    headers, data = None, None
    http3_layer = layers.get('http3')
    # if type(http_layer) is list:
    #    for l in http_layer:
    #        parse_single_http_layer(l)
    # else:
    #    parse_single_http2_layer(http2_layer)
    return headers, data


def parse_http(layers: dict, layer_names: list):
    headers, data = None, None
    http_layer = layers.get('http')
    data = http_layer.get('http_http_file_data', '')
    raw_headers = None
    if 'http_http_response_line' in http_layer:
        raw_headers = http_layer.get('http_http_response_line')
    if 'http_http_request_line' in http_layer:
        raw_headers = http_layer.get('http_http_request_line')
    headers = {}
    for line in raw_headers:
        i = line.find(': ')
        name = line[:i].strip()
        value = line[i + 1:].strip()
        headers[name] = value
    if 'http_http_response_for_uri' in http_layer:
        headers['uri'] = http_layer.get('http_http_response_for_uri')
    elif 'http_http_request_full_uri' in http_layer:
        headers['uri'] = http_layer.get('http_http_request_full_uri')
    headers['is_request'] = 'http_http_request' in http_layer
    return [{'headers': headers, 'data': data}]

    # 'http_http_request_line' // request headers
    # 'http_http_request_method'
    # 'http_http_request_full_uri'
    # 'http_http_file_data' // data if sent

    # 'http_http_response_code' (+ 'http_http_response_code_desc' pour lisibilité)
    # 'http_http_response_line' // response headers
    # 'http_http_response_for_uri' // uri which replies
    # 'http_http_file_data'

    # if type(http_layer) is list:
    #    for l in http_layer:
    #        parse_single_http_layer(l)
    # else:
    #    parse_single_http2_layer(http2_layer)


def get_top_most_layers(packet, protocol, protocol_stack):
    i = protocol_stack.find(f':{protocol}')
    top_most_layer_names = protocol_stack[i + 1:].split(':')
    top_most_layers = {k: packet.get('layers').get(k) for k in top_most_layer_names}
    return top_most_layers, top_most_layer_names


def dispatch(packet):
    protocol_stack = packet.get('layers').get('frame').get('frame_frame_protocols')
    packets = []
    packet_description = {
        'src': {},
        'dst': {},
        'timestamp': packet.get('timestamp'),
        'community_id': packet.get('layers').get('communityid_communityid'),
        'headers': None,
        'data': None,
        'protocol_stack': protocol_stack
    }
    if 'ip' not in packet.get('layers'):
        return None

    src_ip, dst_ip = parse_ip_layer(packet.get('layers').get('ip'))
    if protocol_stack.startswith('eth:'):
        src_eth, dst_eth = parse_eth_layer(packet.get('layers').get('eth'))
    if protocol_stack.startswith('sll:'):
        src_eth, dst_eth = parse_sll_layer(packet.get('layers').get('sll'))
    packet_description['src'].update(src_ip)
    packet_description['src'].update(src_eth)
    packet_description['dst'].update(dst_ip)
    packet_description['dst'].update(dst_eth)

    if ':http3' in protocol_stack:
        top_most_layers, top_most_layer_names = get_top_most_layers(packet, 'http3', protocol_stack)
        parse_http3(top_most_layers, top_most_layer_names)
        return
    elif ':http2' in protocol_stack:
        top_most_layers, top_most_layer_names = get_top_most_layers(packet, 'http2', protocol_stack)
        ret = parse_http2(top_most_layers, top_most_layer_names)
        for r in ret:
            pd = packet_description.copy()
            if r['headers'] or r['data']:
                pd['headers'] = r['headers']
                pd['data'] = r['data']
                packets.append(pd)
        return packets
    elif ':http' in protocol_stack:
        top_most_layers, top_most_layer_names = get_top_most_layers(packet, 'http', protocol_stack)
        ret = parse_http(top_most_layers, top_most_layer_names)
        for r in ret:
            pd = packet_description.copy()
            if r['headers'] or r['data']:
                pd['headers'] = r['headers']
                pd['data'] = r['data']
                packets.append(pd)
        return packets


def view_decrypted_traffic():
    arg_parser = argparse.ArgumentParser(prog='pirogue', description='View decrypted TLS traffic')
    arg_parser.add_argument('-i', '--input', dest='infile', type=argparse.FileType('r'), required=True,
                        metavar='INPUT_FILE', help='The JSON file generated by tshark tshark -2 -T ek --enable-protocol communityid -Ndmn <pcapng file> > <output json file>')
    args = arg_parser.parse_args()
    json_file = args.infile

    if not json_file.name.endswith('.json'):
        console.log('Wrong format of input file. JSON is expected')
        return

    for line in json_file.readlines():
        if line.startswith('{"timestamp":'):
            packet = json.loads(line)
            d = dispatch(packet)
            if not d:
                continue
            for p in d:
                try:
                    if p.get('data'):
                        source = p.get('src').get('ip') + ' / ' + p.get('src').get('host')
                        destination = p.get('dst').get('ip') + ' / ' + p.get('dst').get('host')
                        console.rule(f"[purple] {source} -> {destination}", align='left')
                        console.print(f"[plum4]Community ID: {p.get('community_id')}")
                        console.print(p.get('headers'))
                        console.print(p.get('data'))
                except:
                    pass