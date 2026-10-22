# xArm7 Teleop

GELLO 리더암이나 휴대폰으로 xArm7을 조작하고, pi0 학습용 시연을 수집하는 개인 로봇 실험 프로젝트.
장비 점검부터 텔레옵·녹화·정책 학습·재생 진단까지 한 작업 환경으로 정리했다.

- **성격:** 개인 로봇 실험
- **주요 작업:** GELLO·WebXR 텔레옵 · 로컬 순기구학 · 시연 수집 · 재생 진단
- **기술:** Python · LeRobot · OpenPI · xArm SDK · RealSense · WebXR

![xArm7 로컬 제어판](docs/images/gui-control-panel.png)

<sub>환경 점검, 조작, 녹화, 복구 스크립트를 실행하는 로컬 제어판.</sub>

## 프로젝트 개요

| 작업 | 내용 |
| --- | --- |
| 원격 조작 | GELLO 관절·끝점 추적, 휴대폰 WebXR 6-DoF 입력 |
| 시연 수집 | 손목 RealSense 등 여러 카메라와 관절 정보를 LeRobot 형식으로 기록 |
| 정책 학습 | OpenPI pi0의 A6000 48GB LoRA·COSS AGPU Full 학습 절차 |
| 재생·진단 | 시연 리플레이, 목표와 실제 움직임 비교, 오류 복구 |

## 구현 내용

GELLO의 초기 엔코더 오차가 끝점 추적에 영향을 주는 문제를 다뤘다.
팔로워의 기준 관절에 리더의 변화량을 더하는 방식으로 바꾸고, 로컬 순기구학을 구현해
30Hz 제어 루프의 네트워크 왕복을 줄였다. 텔레옵 코드는
[UFACTORY 통합 저장소의 포크](https://github.com/sesepark/lerobot_robot_ufactory/tree/xarm7-gello-webxr)에 있다.

## 재생 진단

재생이 원래 시연보다 거칠게 움직이는 문제는 목표 action과 관측 궤적을 비교해 확인했다.
아래 진단에서는 두 신호의 최대 요구 속도가 각각 76.09°/s와 39.36°/s였다.

![재생 진단: 목표 action과 관측 궤적의 요구 속도](docs/images/replay-diagnosis.png)

<sub>같은 시연에서도 목표와 실제 관측은 다르다. [설계·진단 기록](docs/design-notes.md)에 원인과 재생 방식의 차이를 남겼다.</sub>

## 시작하기

실제 장비에 맞춘 워크스페이스이므로 [팀원용 장비 안내](05_팀원_공유용_xArm7_사용_안내.md)의
안전 규칙과 오류 대응을 먼저 확인한다. 이후 [환경 설정](01_환경설정_안내.md)을 따라
LeRobot·OpenPI 환경을 준비하고, [GUI 안내](04_GUI_제어판_사용_안내.md)로 제어판을 실행한다.

GUI는 `127.0.0.1`에서 열리며 허용된 실행 스크립트만 호출한다.
텔레옵·녹화·카메라·복귀는 한 번에 한 모드만 사용하고, 모드 전환에는 초기 자세 복귀 절차가 있다.

## 문서

| 문서 | 내용 |
| --- | --- |
| [환경 설정](01_환경설정_안내.md) | Python·LeRobot·OpenPI 환경 분리 |
| [GUI 제어판](04_GUI_제어판_사용_안내.md) | 조작·녹화·상태 확인 |
| [장비 운용](05_팀원_공유용_xArm7_사용_안내.md) | 안전 규칙, 시작 절차, 오류 코드 |
| [WebXR](07_WebXR_휴대폰_텔레옵_사용_안내.md) · [iPhone](08_iPhone_WebXR_텔레옵_사용_안내.md) | 휴대폰 연결과 조작 |
| [서버 학습](02_OpenPI_서버_학습_안내.md) · [A6000 LoRA](03_OpenPI_A6000_48GB_LoRA_학습_안내.md) · [COSS Full](06_팀원_COSS_AGPU_기준_OpenPI_Full_학습.md) | pi0 학습 절차 |
| [설계·진단 기록](docs/design-notes.md) | 제어 구조, 기여 내용, 재생 진단 |

## 사용 범위와 한계

- 로봇 IP와 워크스페이스 경로가 현재 장비 기준으로 고정되어 있다. 다른 환경에서는 설정과 스크립트를 수정해야 한다.
- 데이터셋과 학습 체크포인트는 저장소에 포함하지 않는다.
- GUI가 실제로 동작하려면 `uf_lerobot` 환경, `run.sh`, 로봇 연결이 필요하다.
- WebXR 인증서는 로컬에서 발급하며 포함하지 않는다. C31 외의 오류는 자동 해제하지 않는다.

## 관련 프로젝트

- [텔레옵 구현 포크](https://github.com/sesepark/lerobot_robot_ufactory/tree/xarm7-gello-webxr) — GELLO·로컬 FK·WebXR 구현
- [원본 UFACTORY 통합](https://github.com/xArm-Developer/lerobot_robot_ufactory) · [OpenPI](https://github.com/Physical-Intelligence/openpi)
- [SO-ARM101 Console](https://github.com/sesepark/soarm101-console) — 다른 로봇팔에서 진행한 원격조작·시연 수집 프로젝트
