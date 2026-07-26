import 'package:shared_preferences/shared_preferences.dart';

class SavedConnection {
  const SavedConnection({this.host, this.port, this.gain});

  final String? host;
  final int? port;
  final double? gain;
}

class ConnectionPreferences {
  static const _hostKey = 'receiver_host';
  static const _portKey = 'receiver_port';
  static const _gainKey = 'transmit_gain';

  final SharedPreferencesAsync _preferences = SharedPreferencesAsync();

  Future<SavedConnection> load() async {
    return SavedConnection(
      host: await _preferences.getString(_hostKey),
      port: await _preferences.getInt(_portKey),
      gain: await _preferences.getDouble(_gainKey),
    );
  }

  Future<void> save({
    required String host,
    required int port,
    required double gain,
  }) async {
    await Future.wait<void>([
      _preferences.setString(_hostKey, host),
      _preferences.setInt(_portKey, port),
      _preferences.setDouble(_gainKey, gain),
    ]);
  }
}
