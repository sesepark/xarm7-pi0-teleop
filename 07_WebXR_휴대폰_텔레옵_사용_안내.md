# xArm7 WebXR 휴대폰 텔레옵 사용 안내

> iPhone은 최신 권장 앱과 설정을 반영한
> [iPhone 전용 안내](./08_iPhone_WebXR_텔레옵_사용_안내.md)를 먼저 따르세요.

## 1. 리더 선택

기존 GELLO는 삭제되지 않았으며 아래 세 모드를 독립적으로 선택할 수 있습니다.

| 명령 | 리더 | 로봇 제어 방식 |
|---|---|---|
| `./run.sh teleop joint` | GELLO | 관절 추종 |
| `./run.sh teleop endpoint` | GELLO | TCP endpoint 추종 |
| `./run.sh teleop webxr` | 휴대폰 WebXR | TCP endpoint 추종 |

녹화도 `./run.sh record joint`, `./run.sh record endpoint`,
`./run.sh record webxr` 중 하나를 선택합니다.

## 2. 현재 적용된 WebXR 안전값

- 휴대폰 이동량의 0.5배를 xArm TCP 이동으로 사용
- 휴대폰 회전량의 0.5배를 xArm TCP 회전으로 사용
- xArm 정상 TCP 속도 최대 100mm/s
- 시작 후 첫 3초 TCP 속도 20mm/s
- MOVE 버튼을 누르는 동안만 팔 이동
- MOVE를 놓으면 최신 실제 xArm TCP pose를 hold target으로 사용
- pose가 250ms 이상 끊기거나 한 프레임에 50mm/20° 이상 점프하면 safety hold
- 한 번에 휴대폰 한 대만 접속 가능
- 실행할 때마다 새로운 pairing token 생성

WebXR 네트워크 스레드는 xArm API를 직접 호출하지 않습니다. 검증된 최신 pose만
기존 LeRobot 30Hz 제어 루프에 전달합니다.

## 3. PC 준비

프로젝트 경로에서 다음 명령을 실행합니다.

```bash
cd /home/robotics/pi0_sehwan
./run.sh webxr-setup
```

현재 PC에는 이미 필요한 Python 패키지와 인증서가 준비되어 있습니다. 다만 PC의
Wi-Fi/Ethernet IP가 바뀌면 반드시 `./run.sh webxr-setup`을 다시 실행해야 합니다.

휴대폰에 복사할 파일은 다음 하나뿐입니다.

```text
/home/robotics/pi0_sehwan/runtime/webxr_tls/webxr-local-ca.crt
```

`webxr-local-ca.key`와 `server.key`는 비밀키이므로 휴대폰이나 메신저로 복사하지
마세요.

## 4. Android 휴대폰 설정

1. PC와 휴대폰을 같은 Wi-Fi에 연결합니다.
2. Chrome을 최신 버전으로 업데이트합니다.
3. Play 스토어에서 `Google Play Services for AR`을 설치하거나 업데이트합니다.
4. USB 케이블 등으로 `webxr-local-ca.crt`만 휴대폰에 복사합니다.
5. Android 설정에서 CA 인증서를 설치합니다.
   - 일반 Android: `설정 → 보안 및 개인정보 보호 → 기타 보안 설정 → 인증서 설치 → CA 인증서`
   - Samsung: `설정 → 보안 및 개인정보 보호 → 기타 보안 설정 → 기기 저장공간에서 설치 → CA 인증서`
6. 경고가 나오면 인증서 이름을 `pi0 WebXR Local CA`로 지정해 설치합니다.
7. Chrome을 완전히 종료했다가 다시 엽니다.

기기 메뉴 이름은 Android 제조사/버전에 따라 조금 다를 수 있습니다.

## 5. iPhone 설정

Safari는 WebXR immersive AR을 지원하지 않으므로 App Store에서 `XR Browser` 또는
`WebXR Viewer`가 필요합니다.

1. PC와 iPhone을 같은 Wi-Fi에 연결합니다.
2. `webxr-local-ca.crt`를 AirDrop, USB 파일 공유 등으로 iPhone에 복사합니다.
3. 인증서 프로파일을 설치합니다.
   - `설정 → 일반 → VPN 및 기기 관리 → 다운로드된 프로파일 → 설치`
4. 설치 후 CA를 완전히 신뢰하도록 설정합니다.
   - `설정 → 일반 → 정보 → 인증서 신뢰 설정`
   - `pi0 WebXR Local CA`의 전체 신뢰를 켭니다.
5. XR Browser 또는 WebXR Viewer를 열어 터미널에 표시되는 URL로 접속합니다.

서드파티 iOS WebXR 앱은 기기/iOS 버전에 따라 동작 차이가 있으므로 Android Chrome을
우선 권장합니다.

## 6. 로봇 없이 휴대폰만 시험

먼저 반드시 이 시험을 합니다.

```bash
cd /home/robotics/pi0_sehwan
./run.sh webxr-phone-test
```

이 명령은 xArm에 연결하지 않으며 로봇 모션 명령도 만들지 않습니다.

1. 터미널에 표시된 `https://192.168...:8443/?token=...` URL 전체를 휴대폰에서 엽니다.
2. 페이지의 Server 상태가 `connected`인지 확인합니다.
3. `START WEBXR`을 누르고 카메라 권한을 허용합니다.
4. WebXR 상태가 `tracking`이며 약 30fps인지 확인합니다.
5. MOVE를 눌렀다 놓았을 때 터미널의 `move=True/False`가 바뀌는지 확인합니다.
6. GRIPPER를 눌렀을 때 `gripper_closed=True/False`가 바뀌는지 확인합니다.
7. PC에서 `Ctrl+C`로 종료합니다.

인증서 경고 페이지가 뜨면 CA 설치 또는 전체 신뢰가 완료되지 않은 것입니다. 경고를
무시하고 접속하지 말고 인증서 설정을 먼저 해결하세요.

## 7. 실제 xArm 저속 시험

작업영역에서 사람, 물체, 케이블을 치운 뒤 진행합니다.

```bash
cd /home/robotics/pi0_sehwan
./run.sh teleop webxr
```

순서는 다음과 같습니다.

1. 읽기 전용 검증 결과가 모두 OK인지 확인합니다.
2. 터미널 요구에 따라 `start`를 입력합니다.
3. xArm 초기화가 끝나고 WebXR URL이 출력될 때까지 기다립니다.
4. 휴대폰에서 URL을 열고 `START WEBXR`을 누릅니다.
5. 휴대폰 MOVE는 누르지 않은 상태로 둡니다.
6. PC 키보드에서 `Space`를 눌러 WebXR teleop을 arm합니다.
7. 휴대폰 MOVE를 짧게 누른 채 휴대폰을 1~2cm만 움직여 축 방향을 확인합니다.
8. MOVE를 놓았을 때 로봇이 즉시 hold하는지 확인합니다.
9. 방향과 hold가 모두 맞을 때만 이동 범위를 조금씩 늘립니다.

기본 좌표 방향은 다음과 같습니다.

- 휴대폰을 카메라가 보는 앞쪽으로 이동 → xArm +X
- 휴대폰을 왼쪽으로 이동 → xArm +Y
- 휴대폰을 위로 이동 → xArm +Z

MOVE를 놓은 상태에서는 휴대폰을 편한 위치로 옮길 수 있습니다. 다시 MOVE를 누르는
순간 현재 휴대폰/xArm pose가 새로운 상대 영점이 됩니다.

종료는 MOVE를 먼저 놓은 뒤 PC에서 `Space`로 pause하고 `ESC` 또는 `Ctrl+C`를
사용합니다.

## 8. WebXR로 데이터 녹화

저속 실제 시험이 성공한 뒤에만 실행합니다.

```bash
./run.sh record webxr 20
```

기존 GELLO 기록과 섞이지 않도록 WebXR 전용 dataset/repo 이름을 사용합니다. 이후의
성공 저장, 실패 폐기, 자동 초기 자세 복귀 방식은 기존 record 흐름과 같습니다.

## 9. 자주 발생하는 문제

### `navigator.xr` 또는 `immersive-ar` 미지원

- Android: Chrome과 Google Play Services for AR 업데이트 여부를 확인합니다.
- 휴대폰이 ARCore 지원 기기인지 확인합니다.
- iPhone Safari가 아니라 XR Browser/WebXR Viewer를 사용합니다.

### 인증서 오류

- PC IP가 바뀌었으면 `./run.sh webxr-setup`을 다시 실행합니다.
- 새 CA를 만든 경우 휴대폰의 이전 CA를 제거하고 새 CA를 설치합니다.
- iPhone은 프로파일 설치 후 `인증서 신뢰 설정`에서 전체 신뢰도 별도로 켜야 합니다.

### Server disconnected

- PC와 휴대폰이 같은 Wi-Fi인지 확인합니다.
- 게스트 Wi-Fi/AP isolation이 켜져 있으면 같은 Wi-Fi여도 서로 접속할 수 없습니다.
- 다른 휴대폰/브라우저 탭이 이미 접속했다면 먼저 닫습니다.

### `WebXR safety hold`

- MOVE를 놓습니다.
- PC에서 Space로 pause합니다.
- 조명, 카메라 가림, 너무 빠른 휴대폰 움직임을 해결합니다.
- 휴대폰 tracking이 안정된 뒤 Space로 다시 arm합니다.

## 10. 구현 참고

WebXR 좌표계 변환과 relative-pose 방식은 Apache-2.0의
[SpesRobotics/teleop](https://github.com/SpesRobotics/teleop) 구현을 참고했으며,
이 프로젝트에서는 기존 LeRobot 루프, deadman hold, stale timeout, 단일 클라이언트,
입력 검증 및 저속 제한을 별도로 구현했습니다.
