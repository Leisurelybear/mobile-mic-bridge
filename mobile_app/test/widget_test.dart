import 'package:flutter_test/flutter_test.dart';
import 'package:mobile_mic_bridge/main.dart';

void main() {
  testWidgets('shows connection form', (tester) async {
    await tester.pumpWidget(const MobileMicApp());
    expect(find.text('Mobile Mic Bridge'), findsOneWidget);
    expect(find.text('开始传输'), findsOneWidget);
    expect(find.text('Windows IP 地址'), findsOneWidget);
  });
}
