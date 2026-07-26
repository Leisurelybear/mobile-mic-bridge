import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:nsd/nsd.dart' as nsd;

class DiscoveredReceiver {
  const DiscoveredReceiver({
    required this.name,
    required this.host,
    required this.port,
  });

  final String name;
  final String host;
  final int port;

  String get id => '$host:$port';
}

class ReceiverDiscovery extends ChangeNotifier {
  nsd.Discovery? _discovery;
  bool _disposed = false;
  final Map<String, DiscoveredReceiver> _receiversById = {};
  final Map<String, String> _serviceReceiverIds = {};

  List<DiscoveredReceiver> receivers = const [];
  bool scanning = false;
  String status = '正在搜索局域网中的电脑…';

  Future<void> start() async {
    await stop();
    if (_disposed) return;
    scanning = true;
    status = '正在搜索局域网中的电脑…';
    _receiversById.clear();
    _serviceReceiverIds.clear();
    receivers = const [];
    _notify();
    try {
      final discovery = await nsd.startDiscovery(
        '_mobilemic._tcp',
        ipLookupType: nsd.IpLookupType.any,
      );
      if (_disposed) {
        await nsd.stopDiscovery(discovery);
        return;
      }
      _discovery = discovery;
      discovery.addServiceListener(_handleServiceStatus);
    } catch (error) {
      scanning = false;
      status = '自动发现不可用：$error';
      _notify();
    }
  }

  Future<void> refresh() => start();

  Future<void> stop() async {
    final discovery = _discovery;
    _discovery = null;
    if (discovery == null) return;
    discovery.removeServiceListener(_handleServiceStatus);
    await nsd.stopDiscovery(discovery);
  }

  void _handleServiceStatus(
    nsd.Service service,
    nsd.ServiceStatus serviceStatus,
  ) {
    if (_disposed) return;
    final serviceKey = '${service.name}|${service.type}';
    if (serviceStatus == nsd.ServiceStatus.lost) {
      final receiverId = _serviceReceiverIds.remove(serviceKey);
      if (receiverId != null) _receiversById.remove(receiverId);
      _publishReceivers();
      return;
    }
    final port = service.port;
    final host = _serviceHost(service);
    if (port == null || host == null) return;
    final receiver = DiscoveredReceiver(
      name: _serviceName(service),
      host: host,
      port: port,
    );
    final previousId = _serviceReceiverIds[serviceKey];
    if (previousId != null && previousId != receiver.id) {
      _receiversById.remove(previousId);
    }
    _serviceReceiverIds[serviceKey] = receiver.id;
    _receiversById[receiver.id] = receiver;
    _publishReceivers();
  }

  void _publishReceivers() {
    receivers = _receiversById.values.toList()
      ..sort((left, right) => left.name.compareTo(right.name));
    scanning = true;
    status = receivers.isEmpty ? '未发现电脑，可继续手动输入 IP' : '点击电脑即可连接';
    _notify();
  }

  String? _serviceHost(nsd.Service service) {
    final addresses = service.addresses ?? const <InternetAddress>[];
    for (final address in addresses) {
      if (address.type == InternetAddressType.IPv4) return address.address;
    }
    final host = service.host?.replaceFirst(RegExp(r'\.$'), '');
    return host == null || host.isEmpty ? null : host;
  }

  String _serviceName(nsd.Service service) {
    final name = service.name ?? 'Windows Receiver';
    return name.replaceFirst(
      RegExp(r'\._mobilemic\._tcp\.local\.?$'),
      '',
    );
  }

  void _notify() {
    if (!_disposed) notifyListeners();
  }

  @override
  void dispose() {
    _disposed = true;
    final discovery = _discovery;
    _discovery = null;
    if (discovery != null) {
      discovery.removeServiceListener(_handleServiceStatus);
      nsd.stopDiscovery(discovery);
    }
    super.dispose();
  }
}
