import 'package:flutter_test/flutter_test.dart';
import 'package:mobile_mic_bridge/main.dart';
import 'package:shared_preferences_platform_interface/in_memory_shared_preferences_async.dart';
import 'package:shared_preferences_platform_interface/shared_preferences_async_platform_interface.dart';

void main() {
  testWidgets('shows connection form', (tester) async {
    SharedPreferencesAsyncPlatform.instance =
        InMemorySharedPreferencesAsync.empty();
    await tester.pumpWidget(const MobileMicApp());
    expect(find.text('Mobile Mic Bridge'), findsOneWidget);
    expect(find.text('开始传输'), findsOneWidget);
    expect(find.text('Windows IP 地址'), findsOneWidget);
    expect(find.text('自动发现 Windows'), findsOneWidget);
    expect(find.text('发送音量'), findsOneWidget);
  });
}
