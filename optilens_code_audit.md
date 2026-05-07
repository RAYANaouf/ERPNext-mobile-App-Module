# 🔍 Optilens Flutter App — Full Code Audit

> **Audited:** `lib/` directory — 14 controllers, 11 repositories, 19 domain models, 10+ views, 7 utils/widgets
> **Stack:** Flutter · GetX · `http` · `shared_preferences` · Frappe/ERPNext backend

---

## 1. Architecture — **7.5 / 10**

### What pattern is used?
A **GetX-flavoured layered architecture** with three clear layers:

| Layer | Folder | Role |
|---|---|---|
| **Data** | `lib/data/repositories/` | HTTP calls, JSON parsing |
| **Domain** | `lib/domain/response/` | Pure Dart models |
| **Application** | `lib/application/controllers/` | Business logic, reactive state |
| **Presentation** | `lib/views/`, `lib/widgets/` | UI, `Obx` bindings |
| **Cross-cutting** | `lib/core/services/`, `lib/utils/`, `lib/app/` | Session, routing, config |

### ✅ Strengths
- Layers are well separated — no raw HTTP code in views.
- `SessionService` (GetxService) + `SessionController` dual-layer is clever: one handles persistence, the other reactive state.
- `AppBinding` / `LoginBinding` with `lazyPut` is correct GetX DI usage — controllers are created on demand.
- Detail pages (`InvoiceDetailController`, `StockEntryDetailsController`) are re-registered fresh per push via `BindingsBuilder`, preventing stale state bugs.
- `RepositoryException` typed error class is a solid contract.
- `AppRoutes` centralises all named routes cleanly.

### ⚠️ Areas to Improve

**1. Missing repository abstractions (interfaces)**  
Repositories are concrete classes instantiated directly inside controllers. There are no abstract interfaces, making the code hard to unit-test and tightly coupled.

```dart
// ❌ Current — hard to mock
class OrderController extends GetxController {
  final _repo = OrderRepository();   // concrete, not injectable
}

// ✅ Better — inject via constructor/interface
abstract class IOrderRepository {
  Future<List<Item>> fetchItems(String code);
  Future<bool> submitOrder(List<Map<String, dynamic>> items);
}

class OrderController extends GetxController {
  final IOrderRepository _repo;
  OrderController({required IOrderRepository repo}) : _repo = repo;
}
// Registered: Get.lazyPut(() => OrderController(repo: OrderRepository()))
```

**2. `domain/response/` naming is misleading**  
This folder contains domain models (not API response wrappers). Some files mix: pure models (`Item`, `CartItem`) sit alongside DTO-style classes (`InvoicesResponse`, `PaymentResponse`). Consider splitting into `domain/models/` and `data/dto/`.

**3. `payment_utils.dart` is a layer-violation**  
`PaymentList` (a full `StatelessWidget`) and `PaymentItemData` (a view-model) live in `utils/`. Widgets should be in `widgets/` or `views/`; view-model data classes should be in `application/`.

**4. `invoice_utils.dart` / `announcement_utils.dart` follow the same anti-pattern**  
These files contain `StatelessWidget` classes (`InvoiceList`, `AnnouncementCard`) mixed with business logic. They belong in `widgets/`.

**5. No domain layer logic**  
`domain/response/` only has data-bags with `fromJson`. There is zero domain logic here — all business rules live in controllers. For a small app this is fine, but it's worth being intentional about.

---

## 2. State Management — **8 / 10**

### Solution used: **GetX (`get: ^4.7.2`)**

### ✅ Strengths
- `Obx()` / `.obs` used consistently; no raw `setState` in sight.
- `Rxn<T>` used correctly for nullable reactive values (`customer`, `error`, `selectedDevice`).
- `ScrollController` and `TextEditingController` are always disposed in `onClose()` (✅ `DashboardController`, `InvoiceController`, `LoginController`, `UserDashboardController`).
- `Get.lazyPut` prevents eager controller creation; permanent controllers in `main()` are appropriate.
- `cart.refresh()` after in-place mutations — correctly triggers Obx rebuild.

### ⚠️ Areas to Improve

**1. `loadOrders()` called inside `build()` in `OrderHistoryPage`**  
This is the most critical state bug. Every time the widget rebuilds, a network call fires.

```dart
// ❌ Current — fires on EVERY rebuild
@override
Widget build(BuildContext context) {
  final c = Get.find<OrderController>();
  c.loadOrders(); // ← DANGEROUS: called in build()
  ...
}

// ✅ Fix — use onInit() in the controller, or trigger in a binding
// In the controller:
@override
void onInit() {
  super.onInit();
  loadOrders();  // ← called once when controller is created
}

// In GetPage (main.dart):
GetPage(
  name: AppRoutes.orderHistory,
  page: () => const OrderHistoryPage(),
  binding: BindingsBuilder(() => Get.put(OrderHistoryController())),
)
```

**2. `c.cart.clear()` called inside `build()` in `OrderPage`**  
Same category of issue — side effects inside `build()` cause unexpected state resets on hot-reload and tab switches.

```dart
// ❌ Current
Widget build(BuildContext context) {
  final c = Get.find<OrderController>();
  c.cart.clear();  // ← side effect in build()

// ✅ Fix: clear cart in onInit() of a dedicated controller,
//         or on route arrival via Get.arguments / binding
```

**3. `OrderController` is a God Controller**  
It manages item catalogue, cart, order history, AND search — four distinct concerns in one class. As the app grows this becomes unwieldy. Consider splitting `CartController` and `OrderHistoryController`.

**4. `DashboardPage` and `InvoicePage` are not `const` and hold controller references as instance fields**  
```dart
// dashboard_view.dart
class DashboardPage extends StatelessWidget {
  DashboardPage({super.key}); // ← not const

  final DashboardController c = Get.find<DashboardController>(); // ← field init
```
This is benign in practice with GetX but creates a subtle issue: if the widget is reconstructed, `Get.find` runs again during field initialization — before `build()`. Prefer finding inside `build()` for clarity and safety.

**5. `_ClientShell` pages list is not const**
```dart
// ❌ Current
final List<Widget> _pages = [
  DashboardPage(),   // new instances on every _ClientShell build
  InvoicePage(),
  ...
];

// ✅ Fix: make pages static or pass them from a parent that won't rebuild
```

---

## 3. Code Quality — **7 / 10**

### ✅ Strengths
- Naming is consistent and readable (snake_case files, PascalCase classes, camelCase members).
- Controllers are reasonably decomposed — one per feature.
- Most files are under 200 lines; `order_history_page.dart` (310 lines) and `order_page.dart` (323 lines) are the longest views — still acceptable.
- Good use of private methods (`_buildTopBar`, `_buildOrderCard`, etc.) to keep `build()` clean.
- `flutter_lints` is enabled.
- API URLs are centralised in `ApiConfig`.
- Comments are present and useful (especially in `CartItem` and `AppBinding`).

### ⚠️ Areas to Improve

**1. `reclamation.dart` uses Windows CRLF line endings (`\r\n`)** while all other files use LF. This causes diff noise and should be normalised.

**2. `dashboard_view.dart` uses a wrong relative import**
```dart
// ❌ Current (uses ../ three times from lib/views/client/)
import '../../../application/controllers/dashboard_controller.dart';

// ✅ Fix: use package imports everywhere
import 'package:optilens/application/controllers/dashboard_controller.dart';
```
`invoice_view.dart`, `complaint_form_view.dart` all have the same inconsistency — some imports use relative paths (`../../`) and some use package paths. Pick one style and stick to it.

**3. Hardcoded color values scattered across views**  
`const Color(0xFF008075)`, `const Color(0xFF1F2837)` are repeated in at least 5 files. Define a central theme/palette.

```dart
// lib/core/theme/app_colors.dart
abstract class AppColors {
  static const teal     = Color(0xFF008075);
  static const darkBlue = Color(0xFF1F2837);
  static const bgLight  = Color(0xFFF7FFFD);
}
```

**4. `_buildOutstandingCard(customer)` in `dashboard_view.dart` types `customer` as `dynamic`**
```dart
// ❌
Widget _buildOutstandingCard(customer) { // dynamic parameter
// ✅
Widget _buildOutstandingCard(Customer customer) {
```

**5. Magic strings in order status**  
`_statusColor()` in `OrderHistoryPage` uses inline string literals (`'draft'`, `'to deliver'`). These should be enums or constants.

**6. Zero tests**  
No `test/` directory found. For a commercial app hitting a live backend, at minimum unit-testing controllers with mocked repositories is recommended.

**7. `analysis_options.yaml` has no custom rules enabled**  
The default `flutter_lints` set is minimal. Consider enabling:
```yaml
linter:
  rules:
    prefer_single_quotes: true
    avoid_print: true
    prefer_const_constructors: true
    prefer_const_declarations: true
    always_declare_return_types: true
```

---

## 4. Performance — **6.5 / 10**

### ✅ Strengths
- All list views use `ListView.builder` ✅ (`order_history_page.dart`, `order_page.dart`, `invoice_detail_page.dart`).
- Pagination implemented correctly in `InvoiceController` and `UserDashboardController` (limit/offset with infinite scroll).
- `SearchAnchor` / `suggestionsBuilder` uses async server-side search, avoiding full client-side filtering for the search flow.
- Scroll-based header hide/show in `InvoiceController` is done efficiently in the controller, not in `build()`.
- `DashboardController` uses `Future.wait` for parallel data fetching ✅.

### ⚠️ Areas to Improve

**1. `c.loadOrders()` inside `build()` — repeated network call** (covered in §2, critical)

**2. `c.cart.clear()` inside `build()` in `OrderPage`** (covered in §2)

**3. No `const` constructors on many widgets**  
Most helper widgets (`_buildOrderCard`, `_buildItemTile`) create new `BoxDecoration`, `TextStyle`, etc. on every rebuild. Using `const` where possible avoids unnecessary allocations.

```dart
// ❌
style: TextStyle(fontWeight: FontWeight.bold, fontSize: 14)

// ✅
style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 14)
```

**4. `FutureBuilder` inside a `BottomSheet` re-fires on every sheet open**  
`_showOrderDetails` uses `FutureBuilder(future: c.getOrderItems(orderId))`. Each time the user opens the sheet, a new HTTP call is made. There's no caching.

```dart
// ✅ Minimal fix: cache the result in the controller
final _orderItemsCache = <String, List<dynamic>>{}.obs;

Future<List<dynamic>?> getOrderItems(String orderId) async {
  if (_orderItemsCache.containsKey(orderId)) return _orderItemsCache[orderId];
  final result = await _repo.getOrderItems(orderId);
  if (result != null) _orderItemsCache[orderId] = result;
  return result;
}
```

**5. No image caching — `cached_network_image` not used**  
`Image.asset` is used for local images (fine), but if/when remote images are added, `CachedNetworkImage` should be the default. The package is not in `pubspec.yaml`.

**6. `filteredItems` / `filteredSalesItems` / `filteredPOSItems` are computed getters with no memoization**  
Every `Obx` rebuild calls `.where().map().toList()` on potentially hundreds of items. For large lists, add debounce + `ever()` to compute once and store in an `RxList`.

```dart
// ✅ Debounced + cached filtered list
final _filteredItems = <Item>[].obs;

@override
void onInit() {
  super.onInit();
  debounce(searchQuery, (_) => _recomputeFilter(), time: const Duration(milliseconds: 300));
  ever(items, (_) => _recomputeFilter());
}

void _recomputeFilter() {
  final q = searchQuery.value.toLowerCase().trim();
  _filteredItems.value = q.isEmpty
      ? items.toList()
      : items.where((i) => i.itemName.toLowerCase().contains(q)).toList();
}
```

**7. `PrintTicketSmall` is a 50-line method in the controller**  
Bluetooth printing commands are business logic, but the formatting (string padding, layout) belongs in a dedicated `ReceiptFormatter` helper to keep the controller lean and the formatter testable.

---

## 5. Error Handling — **6 / 10**

### ✅ Strengths
- `RepositoryException` typed error class allows clean `rethrow` chains ✅.
- `.timeout(const Duration(seconds: 15))` set on most HTTP calls ✅.
- `TimeoutException` caught and wrapped as `RepositoryException` in `OrderRepository` ✅.
- `error` reactive field in `InvoiceDetailController` surfaces errors to the UI ✅.
- `SessionController._restoreSession()` calls `logout()` on failure ✅.

### ⚠️ Areas to Improve

**1. Silent `catch (_) {}` in 7 controllers — errors swallowed without user feedback**

```dart
// ❌ DashboardController — errors silently dropped
Future<void> _fetchInvoices() async {
  try {
    final r = await _invoiceRepo.fetchInvoices(_customerCode, limit: 5);
    invoices.value = r.salesInvoices;
  } catch (_) {}  // ← user sees nothing if it fails
}

// ❌ PaymentController
} catch (_) {
} finally {
  isLoading.value = false;
}

// ✅ Minimum: show a snackbar or set an error state
} catch (e) {
  Get.snackbar('Erreur', 'Impossible de charger les données',
      backgroundColor: Colors.red, colorText: Colors.white);
}
```

Affected files: `DashboardController`, `PaymentController`, `StockEntryDetailsController`, `OrderController`, `StockEntryDetailsController`, `ComplaintController`.

**2. `confirmOrder()` returns `false` silently on exception**  
The `OrderPage` shows a generic "Erreur de création de commande" message but the actual error from `RepositoryException` is discarded. The user can't tell if it was a timeout, a server error, or a validation failure.

**3. `customer.value!` force-unwrapped in multiple views**
```dart
// ❌ DashboardPage, InvoicePage, ComplaintFormPage
final customer = Get.find<SessionController>().customer.value!;
// If customer is null for any reason → crash with null-check exception
```

```dart
// ✅ Defensive
final customer = Get.find<SessionController>().customer.value;
if (customer == null) {
  Get.offAllNamed(AppRoutes.login);
  return const SizedBox.shrink();
}
```

**4. `reclamation.dart` has a typo in JSON key**
```dart
// ❌ Line 19 — typo: "desciption_reclamation" (missing 'r')
description: json['desciption_reclamation'] ?? "",
```
This will silently return `""` whenever this model is used if the actual API key is `description_reclamation`. Verify against the backend.

**5. `loginRepository` has no timeout**  
`LoginRepository.login()` has no `.timeout()` call, making the login UI freeze indefinitely on network failure.

```dart
// ✅ Add timeout
final response = await http.post(url, ...).timeout(const Duration(seconds: 15));
```

**6. `invoice_repository.dart` has no timeout either** (same issue).

**7. Error state not shown in `OrderController.loadOrders()`**  
Failure silently sets `orders.value = []`, making the UI look like there are no orders — indistinguishable from the "empty" state.

---

## 6. Security — **5.5 / 10**

### ✅ Strengths
- No API keys or secrets found hardcoded in the codebase ✅.
- The production base URL is in `ApiConfig` (not `.env`), which is acceptable for a non-secret endpoint ✅.
- Auth token stored in `SharedPreferences` with 24-hour expiry ✅.
- Session cleared on logout (including legacy keys) ✅.
- No use of `dart:io` for file system access to sensitive paths ✅.

### ⚠️ Areas to Improve

**1. Auth token stored in `SharedPreferences` — not secure**  
`SharedPreferences` stores data in plaintext on Android (`/data/data/<package>/shared_prefs/`) and can be read by rooted devices. For a token, use `flutter_secure_storage` instead.

```yaml
# pubspec.yaml
dependencies:
  flutter_secure_storage: ^9.2.2
```

```dart
// ✅ Replacement in SessionService
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

class SessionService extends GetxService {
  final _storage = const FlutterSecureStorage();

  Future<void> saveSession({...}) async {
    await _storage.write(key: 'auth_token', value: token);
    // ...
  }
}
```

**2. Token passed as a query parameter in multiple GET requests**  
```dart
// stock_entry_details_repository.dart — line 18
final url = Uri.parse('$_baseUrl$_fetchEndpoint?name=$name&token=$token');
```
Tokens in query parameters appear in server logs, browser history, and HTTP referrer headers. They should be passed in the `Authorization` header.

```dart
// ✅ Use Authorization header
final response = await http.get(url, headers: {
  'Authorization': 'token $token',
});
```

**3. No input sanitization on search fields**  
`searchText` from the user goes directly into a URL query parameter. While `Uri.replace(queryParameters: {...})` handles percent-encoding, it's worth noting that server-side injection defences (Frappe ORM) are your only protection.

**4. Client login has no rate-limiting on the client side**  
A user can spam the login button; there's only a visual disable via `isLoading` but a quick double-tap before the first response arrives could submit two requests.

**5. Password field has no minimum validation**  
`loginUser()` only checks if the password is non-empty. A minimum length check should be added.

```dart
// ✅
if (password.length < 8) {
  Get.snackbar('Erreur', 'Le mot de passe doit comporter au moins 8 caractères');
  return;
}
```

**6. `baseUrl` is HTTP-less — verify TLS is enforced**  
`ApiConfig.baseUrl = "https://optilens.jethings.com"` — HTTPS is used ✅. Ensure the server enforces HSTS and has certificate pinning if the app handles medical/financial data.

---

## Summary Table

| Section | Score | Key Issue |
|---|---|---|
| **Architecture** | 7.5/10 | No repository interfaces; widget classes in `utils/` |
| **State Management** | 8/10 | `loadOrders()` / `cart.clear()` inside `build()` |
| **Code Quality** | 7/10 | Mixed import styles; hardcoded colors; zero tests |
| **Performance** | 6.5/10 | Build-time side effects; no filter memoization; no cache |
| **Error Handling** | 6/10 | Silent `catch (_) {}` everywhere; force-unwrap `!`; no timeout on login |
| **Security** | 5.5/10 | Token in plaintext SharedPrefs; token in URL query params |

**Overall: 6.8 / 10** — Solid foundation for a production B2B app, with clear architecture and good GetX usage. The most impactful fixes are: removing side-effects from `build()`, replacing SharedPreferences with secure storage for the auth token, and adding user-facing error messages instead of silent failures.

---

## Priority Action Plan

### 🔴 High Priority (fix now)
1. Move `c.loadOrders()` and `c.cart.clear()` out of `build()` → use `onInit()` / binding
2. Replace `SharedPreferences` with `flutter_secure_storage` for auth token
3. Pass auth token in `Authorization` header, not query string
4. Fix all silent `catch (_) {}` → add user-facing error snackbars
5. Fix `customer.value!` force-unwraps → defensive null checks

### 🟡 Medium Priority (next sprint)
1. Add `LoginRepository` and `InvoiceRepository` HTTP timeouts
2. Fix typo in `reclamation.dart` JSON key (`desciption_reclamation`)
3. Centralise color palette into `AppColors`
4. Move widget classes out of `utils/` → `widgets/`
5. Add `filteredItems` memoization with `debounce` + `ever`
6. Cache `getOrderItems` results to avoid redundant API calls

### 🟢 Low Priority (technical debt)
1. Add repository abstract interfaces for testability
2. Split `OrderController` into `CartController` + `OrderHistoryController`
3. Add `flutter_lints` custom rules (`prefer_single_quotes`, `prefer_const_constructors`)
4. Normalise CRLF → LF in `reclamation.dart`
5. Standardise all imports to package-style
6. Write unit tests for controllers (mock repositories)
