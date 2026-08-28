# iPhone WebXR 텔레옵 사용 안내

## 결론

iPhone Safari는 WebXR AR을 직접 지원하지 않습니다. 현재 가장 간단하고
유지보수 상태가 나은 경로는 [HelloXR](https://apps.apple.com/app/helloxr/id6757726359)
앱을 쓰는 것입니다. HelloXR은 iOS 16 이상에서 네이티브 ARKit 위치/회전
추적을 표준 WebXR API로 연결합니다.

기존 GELLO는 삭제되거나 변경되지 않았습니다.

| 목적 | 명령 |
|---|---|
| GELLO 관절 리더 | `./run.sh teleop joint` |
| GELLO endpoint 리더 | `./run.sh teleop endpoint` |
| iPhone WebXR 리더 | `./run.sh teleop webxr` |

## 1. PC에서 한 번 준비

```bash
cd /home/robotics/pi0_sehwan
./run.sh webxr-setup
```

PC의 IP가 바뀐 뒤에는 위 명령을 다시 실행해야 합니다. iPhone에 복사할
파일은 다음 CA 인증서 하나뿐입니다.

```text
/home/robotics/pi0_sehwan/runtime/webxr_tls/webxr-local-ca.crt
```

`webxr-local-ca.key`와 `server.key`는 비밀키이므로 iPhone, AirDrop, 메신저로
보내지 마세요.

## 2. iPhone 설정

1. iPhone을 iOS 16 이상으로 업데이트하고 PC와 같은 Wi-Fi에 연결합니다.
2. App Store에서 [HelloXR](https://apps.apple.com/app/helloxr/id6757726359)을 설치합니다.
3. Finder에서 `webxr-local-ca.crt`만 AirDrop으로 iPhone에 보냅니다.
4. iPhone에서 인증서 파일을 열어 프로파일을 다운로드합니다.
5. `설정 → 일반 → VPN 및 기기 관리 → 다운로드된 프로파일 → 설치`를 실행합니다.
6. `설정 → 일반 → 정보 → 인증서 신뢰 설정`으로 이동합니다.
7. `pi0 WebXR Local CA`의 **전체 신뢰**를 켭니다. 프로파일 설치만으로는
   HTTPS/WSS 연결이 성공하지 않습니다.

## 3. 로봇 없이 휴대폰만 테스트

```bash
cd /home/robotics/pi0_sehwan
./run.sh webxr-phone-test
```

이 명령은 xArm에 연결하지 않고 모션 명령도 만들지 않습니다.

1. 터미널의 `https://192.168...:8443/?token=...` 주소 **전체**를 복사합니다.
2. Safari가 아니라 **HelloXR 주소창**에 붙여 넣습니다.
3. `Server: connected`를 확인합니다.
4. `START WEBXR`을 누르고 카메라 접근을 허용합니다.
5. `WebXR: tracking` 및 약 30 fps를 확인합니다.
6. `MOVE`를 누르고 놓을 때 PC에 `move=True/False`가 표시되는지 봅니다.
7. `GRIPPER`를 누르면 `gripper_closed=True/False`가 바뀌는지 봅니다.
8. PC에서 `Ctrl+C`로 종료합니다.

## 4. 실제 xArm 저속 테스트

위 휴대폰 단독 테스트가 모두 성공한 뒤에만 실행하세요.

```bash
cd /home/robotics/pi0_sehwan
./run.sh teleop webxr
```

1. PC의 읽기 전용 검증이 모두 `OK`인지 확인합니다.
2. 터미널의 안내에 따라 `start`를 입력합니다.
3. 출력된 URL을 HelloXR에서 열고 `START WEBXR`을 누릅니다.
4. iPhone의 `MOVE`는 누르지 않은 상태로 둡니다.
5. PC 키보드의 `Space`로 WebXR 제어를 arm합니다.
6. `MOVE`를 짧게 누른 채 iPhone을 1~2 cm만 움직여 축 방향을 확인합니다.
7. `MOVE`를 놓았을 때 로봇이 즉시 hold하는지 확인합니다.
8. 이상 방향이나 반응이 보이면 즉시 `MOVE`를 놓고 PC에서 `ESC` 또는
   `Ctrl+C`로 종료합니다.

## 5. 아이폰에서 더 나은 방법 검토

- **지금 바로 쓰기:** HelloXR이 가장 나습니다. 최근 유지보수되며 ARKit을
  쓰고, 현재 서버/웹 UI를 그대로 사용할 수 있습니다.
- **구버전 WebXR Viewer/XR Browser:** 최종 업데이트가 오래되어 우선 권장하지
  않습니다. HelloXR이 안 될 때의 비상 대안으로만 보세요.
- **HelloXR App Clip:** 앱 설치를 줄일 수 있지만 로컬 IP와 사설 CA URL 전달은
  환경별 차이가 있어 초기 셋업에는 전체 앱이 더 확실합니다.
- **전용 네이티브 iOS 앱:** 운영 안정성은 가장 좋을 수 있습니다. ARKit pose를
  WSS로 직접 보내면 브라우저/polyfill 의존성이 없고 CA pinning도 가능합니다.
  다만 Mac, Xcode, Apple 서명 설정이 필요하고 전용 앱 유지보수 비용이 추가됩니다.

현 단계에서는 HelloXR로 실제 지연과 트래킹 안정성을 먼저 측정한 뒤,
필요할 때만 전용 iOS 앱으로 넘어가는 순서가 가장 효율적입니다.

## 6. 문제 해결

- `navigator.xr` 오류: Safari로 열었습니다. 같은 URL을 HelloXR 주소창에 넣으세요.
- 인증서 경고: CA 프로파일 설치 후 `인증서 신뢰 설정`의 전체 신뢰를
  안 켰거나 PC IP가 바뀐 것입니다. `./run.sh webxr-setup`을 다시 실행하세요.
- `Server: disconnected`: 같은 Wi-Fi인지, 게스트 Wi-Fi/AP isolation이 꺼져 있는지
  확인하세요.
- WebXR 시작 후 버튼이 안 보임: HelloXR을 최신 버전으로 업데이트하세요.

## 참고

- [HelloXR App Store](https://apps.apple.com/app/helloxr/id6757726359)
- [HelloXR/ios-webxr 소스](https://github.com/wem-technology/ios-webxr)
- [MDN WebXR Device API](https://developer.mozilla.org/en-US/docs/Web/API/WebXR_Device_API)
- [Apple ARWorldTrackingConfiguration](https://developer.apple.com/documentation/arkit/arworldtrackingconfiguration)
