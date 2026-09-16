import 'dart:async';
import 'dart:collection';
import 'dart:convert';
import 'dart:developer' as developer;
import 'dart:io';

import 'package:app_links/app_links.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_inappwebview/flutter_inappwebview.dart';
import 'package:http/http.dart' as http;
import 'package:path_provider/path_provider.dart';
import 'package:permission_handler/permission_handler.dart';
import 'package:share_plus/share_plus.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:shared_preferences_android/shared_preferences_android.dart';
import 'package:traccar_manager/error_screen.dart';
import 'package:traccar_manager/token_store.dart';
import 'package:url_launcher/url_launcher.dart';

// White-label app name: flutter build ... --dart-define=APP_TITLE="Your Brand"
const kAppTitle = String.fromEnvironment('APP_TITLE', defaultValue: 'DH FleetView');

class MainScreen extends StatefulWidget {
  const MainScreen({super.key});

  @override
  State<MainScreen> createState() => _MainScreenState();
}

class _MainScreenState extends State<MainScreen> {
  static const _urlKey = 'url';
  static const kDefaultUrl = 'https://dhfleetview.co.uk';

  final _initialized = Completer<void>();
  final _authenticated = Completer<void>();

  late final SharedPreferencesWithCache _preferences;
  late final AppLinks _appLinks;
  StreamSubscription<Uri>? _appLinksSubscription;
  final _loginTokenStore = TokenStore();
  InAppWebViewController? _controller;
  String? _loadingError;
  late String _initialUrl;
  bool _settingsReady = false;
  bool _controllerReady = false;

  @override
  void initState() {
    super.initState();
    _initWebView();
    _initAppLinks();
  }

  Future<void> _initAppLinks() async {
    await _initialized.future;
    _appLinks = AppLinks();
    _appLinksSubscription = _appLinks.uriLinkStream.listen((uri) {
      if (uri.scheme == 'com.dhgroup.fleetview') {
        final baseUri = Uri.parse(_getUrl());
        final appPathSegments = [uri.host, ...uri.pathSegments];
        final updatedQueryParameters = Map<String, String>.from(uri.queryParameters);
        if (uri.queryParameters.containsKey('code')) {
          updatedQueryParameters['redirect_uri'] = uri.toString().split('?').first;
        }
        final updatedUri = uri.replace(
          scheme: baseUri.scheme,
          host: baseUri.host,
          port: baseUri.port,
          path: '/${appPathSegments.join('/')}',
          queryParameters: updatedQueryParameters.isEmpty ? null : updatedQueryParameters,
        );
        _loadUrl(updatedUri);
      } else {
        _loadUrl(uri);
      }
    });
  }

  Future<void> _launchAuthorizeRequest(Uri uri) async {
    try {
      final originalRedirect = Uri.parse(uri.queryParameters['redirect_uri']!);
      final redirectSegments = originalRedirect.pathSegments;
      final updatedRedirect = Uri(
        scheme: 'com.dhgroup.fleetview',
        host: redirectSegments.first,
        path: '/${redirectSegments.skip(1).join('/')}',
        queryParameters: originalRedirect.queryParameters.isEmpty ? null : originalRedirect.queryParameters,
      );
      final updatedQueryParameters = Map<String, String>.from(uri.queryParameters)
        ..['redirect_uri'] = updatedRedirect.toString();
      await launchUrl(uri.replace(queryParameters: updatedQueryParameters), mode: LaunchMode.externalApplication);
    } catch (e) {
      developer.log('Failed to launch authorize request', error: e);
    }
  }

  @override
  void dispose() {
    _appLinksSubscription?.cancel();
    super.dispose();
  }

  String _getUrl() {
    // Saved server URL always takes precedence. First launch (or a saved
    // dev/emulator address) falls back to the production server.
    final saved = _preferences.getString(_urlKey);
    final url = saved ?? kDefaultUrl;
    return url.endsWith('/') ? url.substring(0, url.length - 1) : url;
  }

  static const _downloadExtensions = [
    'xlsx', 'xls', 'csv', 'gpx', 'kml', 'kmz', 'pdf', 'exe', 'msi', 'ddd', 'mp4', 'mov', 'avi', 'zip', 'png', 'jpg', 'jpeg',
  ];

  bool _isDownloadable(Uri uri) {
    final path = uri.path.toLowerCase();
    final lastSegment = uri.pathSegments.isNotEmpty ? uri.pathSegments.last.toLowerCase() : '';
    final extension = lastSegment.contains('.') ? lastSegment.split('.').last : '';
    final format = uri.queryParameters['format']?.toLowerCase();
    final downloadQuery = uri.queryParameters['download'] == 'true'
        || (format != null && _downloadExtensions.contains(format));
    // Report exports end in the format itself, e.g. /api/reports/route/xlsx
    // or /api/positions/kml, without a file extension.
    final exportPath = (path.startsWith('/api/reports/') || path.startsWith('/api/positions/'))
        && _downloadExtensions.contains(lastSegment);
    return (extension.isNotEmpty && _downloadExtensions.contains(extension) && !path.startsWith('/assets/'))
        || exportPath
        || lastSegment == 'download'
        || path.contains('/download/')
        || downloadQuery
        || path.contains('/export/');
  }

  String _safeFileName(String value) {
    final cleaned = value.replaceAll(RegExp(r'[^A-Za-z0-9._-]'), '_');
    return cleaned.isEmpty ? 'download' : cleaned;
  }

  String _extensionForMime(String? mimeType) {
    switch (mimeType?.split(';').first.trim().toLowerCase()) {
      case 'application/pdf':
        return 'pdf';
      case 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet':
        return 'xlsx';
      case 'text/csv':
        return 'csv';
      case 'application/gpx+xml':
        return 'gpx';
      case 'application/vnd.google-earth.kml+xml':
        return 'kml';
      case 'application/vnd.google-earth.kmz':
        return 'kmz';
      case 'video/mp4':
        return 'mp4';
      case 'image/png':
        return 'png';
      case 'image/jpeg':
        return 'jpg';
      case 'application/zip':
        return 'zip';
      default:
        return 'bin';
    }
  }

  // Pick a sensible file name: server header, then the page's suggestion, then the URL.
  String _fileNameFor({String? contentDisposition, String? suggested, Uri? uri, String? mimeType}) {
    String? name;
    if (contentDisposition != null && contentDisposition.isNotEmpty) {
      final encoded = RegExp(r"filename\*=(?:UTF-8|utf-8)''([^;]+)").firstMatch(contentDisposition);
      final plain = RegExp(r'filename="?([^";]+)"?').firstMatch(contentDisposition);
      name = encoded != null ? Uri.decodeComponent(encoded.group(1)!) : plain?.group(1);
    }
    if ((name == null || name.trim().isEmpty) && suggested != null && suggested.trim().isNotEmpty) {
      name = suggested;
    }
    if ((name == null || name.trim().isEmpty) && uri != null && uri.pathSegments.isNotEmpty) {
      final last = uri.pathSegments.last;
      name = last.contains('.') ? last : '${last}_${DateTime.now().millisecondsSinceEpoch}';
    }
    name = _safeFileName((name ?? 'download').trim());
    if (!name.contains('.') && mimeType != null) {
      name = '$name.${_extensionForMime(mimeType)}';
    }
    return name;
  }

  Future<Directory> _downloadDirectory() async {
    final base = Platform.isAndroid
        ? (await getExternalStorageDirectory() ?? await getApplicationDocumentsDirectory())
        : await getApplicationDocumentsDirectory();
    final dir = Directory('${base.path}/Downloads');
    if (!await dir.exists()) {
      await dir.create(recursive: true);
    }
    return dir;
  }

  void _showMessage(String message) {
    if (!mounted) return;
    final messenger = ScaffoldMessenger.of(context);
    messenger.hideCurrentSnackBar();
    messenger.showSnackBar(SnackBar(content: Text(message), duration: const Duration(seconds: 3)));
  }

  // Hand the saved file to the system share sheet (Save to Files, Drive, email...).
  // iPad needs an anchor rectangle or the sheet fails to open.
  Future<void> _shareSavedFile(File file, {String? mimeType}) async {
    Rect? origin;
    final box = context.findRenderObject() as RenderBox?;
    if (box != null && box.hasSize) {
      final size = box.size;
      origin = Rect.fromCenter(center: box.localToGlobal(Offset(size.width / 2, size.height / 2)), width: 1, height: 1);
    }
    await SharePlus.instance.share(ShareParams(
      files: [XFile(file.path, mimeType: mimeType)],
      sharePositionOrigin: origin,
    ));
  }

  Future<void> _saveDownloadedBytes(
    Uint8List bytes, {
    String? fileName,
    String? mimeType,
  }) async {
    try {
      final name = _fileNameFor(suggested: fileName, mimeType: mimeType);
      final file = File('${(await _downloadDirectory()).path}/$name');
      await file.writeAsBytes(bytes, flush: true);
      await _shareSavedFile(file, mimeType: mimeType);
    } catch (e) {
      developer.log('Failed to save downloaded file', error: e);
      _showMessage('The file could not be saved. Please try again.');
    }
  }

  // Cookies the WebView holds for this URL, so downloads use the same signed-in
  // session as the page (DH FleetView and the /tacho pages).
  Future<String?> _cookieHeaderFor(Uri uri) async {
    try {
      final cookies = await CookieManager.instance().getCookies(url: WebUri(uri.toString()));
      if (cookies.isEmpty) return null;
      return cookies.map((c) => '${c.name}=${c.value}').join('; ');
    } catch (e) {
      developer.log('Failed to read cookies', error: e);
      return null;
    }
  }

  final Set<String> _activeDownloads = {};

  Future<void> _downloadFile(
    Uri uri, {
    String? suggestedFileName,
    String? mimeType,
  }) async {
    final key = uri.toString();
    if (!_activeDownloads.add(key)) return; // same file already downloading
    final client = http.Client();
    File? file;
    try {
      _showMessage('Downloading…');
      final headers = <String, String>{};
      final cookie = await _cookieHeaderFor(uri);
      if (cookie != null) headers['Cookie'] = cookie;
      final token = await _loginTokenStore.read(false);
      if (token != null && cookie == null) headers['Authorization'] = 'Bearer $token';
      final driverToken = await _driverToken();
      if (driverToken != null && uri.path.startsWith('/tacho/')) headers['Authorization'] = 'Bearer $driverToken';

      final request = http.Request('GET', uri)..headers.addAll(headers);
      final response = await client.send(request);
      if (response.statusCode < 200 || response.statusCode >= 300) {
        developer.log('Failed file download request: ${response.statusCode} $uri');
        await response.stream.drain<void>();
        _showMessage(response.statusCode == 401 || response.statusCode == 403
            ? 'Please sign in again, then retry the download.'
            : 'The file could not be downloaded (${response.statusCode}).');
        return;
      }
      final type = mimeType ?? response.headers['content-type'];
      final name = _fileNameFor(
        contentDisposition: response.headers['content-disposition'],
        suggested: suggestedFileName,
        uri: uri,
        mimeType: type,
      );
      file = File('${(await _downloadDirectory()).path}/$name');
      final sink = file.openWrite();
      await response.stream.pipe(sink);
      await _shareSavedFile(file, mimeType: type);
    } catch (e) {
      developer.log('Failed to download file', error: e);
      _showMessage('The file could not be downloaded. Please try again.');
    } finally {
      client.close();
      _activeDownloads.remove(key);
    }
  }

  // The driver screens keep their sign-in token in localStorage.
  Future<String?> _driverToken() async {
    try {
      final value = await _controller?.evaluateJavascript(
          source: "(function(){try{return JSON.parse(localStorage.getItem('drv:token')||'null')}catch(e){return null}})()");
      return value is String && value.isNotEmpty ? value : null;
    } catch (_) {
      return null;
    }
  }

  void _maybeCompleteInitialized() {
    if (!_initialized.isCompleted && _settingsReady && _controllerReady) {
      _initialized.complete();
    }
  }

  Future<void> _initWebView() async {
    _preferences = await SharedPreferencesWithCache.create(
      sharedPreferencesOptions: Platform.isAndroid
        ? SharedPreferencesAsyncAndroidOptions(backend: SharedPreferencesAndroidBackendLibrary.SharedPreferences)
        : SharedPreferencesOptions(),
      cacheOptions: SharedPreferencesWithCacheOptions(allowList: {'url'}),
    );

    final savedUrl = _preferences.getString(_urlKey);
    if (savedUrl != null
        && (savedUrl.startsWith('http://10.0.2.2')
            || savedUrl.startsWith('http://localhost')
            || savedUrl.startsWith('http://127.0.0.1'))) {
      await _preferences.setString(_urlKey, kDefaultUrl);
    }

    var url = _getUrl();

    setState(() {
      _initialUrl = url;
      _settingsReady = true;
    });

    _maybeCompleteInitialized();
  }

  void _handleWebMessage(String message) async {
    final List<String> parts = message.split('|');
    switch (parts[0]) {
      case 'login':
        if (parts.length > 1) {
          await _loginTokenStore.save(parts[1]);
        }
      case 'authentication':
        final loginToken = await _loginTokenStore.read(true);
        if (loginToken != null) {
          _controller?.evaluateJavascript(source: "handleLoginToken?.('$loginToken')");
        }
      case 'authenticated':
        if (!_authenticated.isCompleted) _authenticated.complete();
      case 'logout':
        await _loginTokenStore.delete();
      case 'download':
        // download|mime|name|base64 (blob: and data: files built in the page)
        try {
          if (parts.length >= 4) {
            await _saveDownloadedBytes(
              base64Decode(parts.sublist(3).join('|')),
              fileName: parts[2],
              mimeType: parts[1],
            );
          } else if (parts.length > 1) {
            // Backwards-compatible format used by older injected pages.
            await _saveDownloadedBytes(
              base64Decode(parts[1]),
              fileName: 'report.xlsx',
              mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            );
          }
        } catch (e) {
          developer.log('Failed to save downloaded file', error: e);
          _showMessage('The file could not be saved. Please try again.');
        }
      case 'downloadUrl':
        // downloadUrl|suggested name|absolute url (links with a download attribute)
        if (parts.length >= 3) {
          final target = Uri.tryParse(parts.sublist(2).join('|'));
          if (target != null && (target.scheme == 'https' || target.scheme == 'http')) {
            await _downloadFile(target, suggestedFileName: parts[1].isEmpty ? null : parts[1]);
          }
        }
      case 'server':
        final url = parts[1];
        await _loginTokenStore.delete();
        await _preferences.setString(_urlKey, url);
        await _loadUrl(Uri.parse(url));
    }
  }

  bool _isRootOrLogin(String baseUrl, String? currentUrl) {
    if (currentUrl == null) return false;
    final baseUri = Uri.parse(baseUrl);
    final currentUri = Uri.parse(currentUrl);
    if (baseUri.origin != currentUri.origin) return false;
    return currentUri.path == '/' || currentUri.path == '/login';
  }

  Future<void> _loadUrl(Uri uri) async {
    await _controller?.loadUrl(urlRequest: URLRequest(url: WebUri(uri.toString())));
  }

  Widget _buildLoadingScreen() {
    return Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          ClipRRect(
            borderRadius: BorderRadius.circular(28),
            child: Image.asset(
              'assets/icon/icon.png',
              width: 96,
              height: 96,
            ),
          ),
          const SizedBox(height: 24),
          const Text(
            kAppTitle,
            style: TextStyle(
              fontSize: 22,
              fontWeight: FontWeight.w700,
              letterSpacing: -0.3,
              color: Color(0xFF1E293B),
            ),
          ),
          const SizedBox(height: 6),
          const Text(
            'TRACKING AND LIVE VIEW',
            style: TextStyle(
              fontSize: 11,
              fontWeight: FontWeight.w600,
              letterSpacing: 1.6,
              color: Color(0xFF64748B),
            ),
          ),
          const SizedBox(height: 28),
          const SizedBox(
            width: 28,
            height: 28,
            child: CircularProgressIndicator(
              strokeWidth: 3,
              color: Color(0xFF4F46E5),
            ),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    if (!_settingsReady) {
      return _buildLoadingScreen();
    }
    if (_loadingError != null) {
      return ErrorScreen(
        error: _loadingError!,
        url: _getUrl(),
        onUrlSubmitted: (url) async {
          await _loginTokenStore.delete();
          await _preferences.setString(_urlKey, url);
          setState(() {
            _initialUrl = url;
            _loadingError = null;
            _controller = null;
            _controllerReady = false;
          });
        },
      );
    }
    return PopScope(
      canPop: false,
      onPopInvokedWithResult: (didPop, result) {
        if (didPop) return;
        _controller?.getUrl().then((url) {
          _controller?.canGoBack().then((canGoBack) {
            if (canGoBack == true && !_isRootOrLogin(_getUrl(), url?.toString())) {
              _controller?.goBack();
            } else {
              SystemNavigator.pop();
            }
          });
        });
      },
      child: Scaffold(
        resizeToAvoidBottomInset: false,
        body: SafeArea(
          maintainBottomViewPadding: true,
          child: InAppWebView(
            key: ValueKey(_initialUrl),
            initialUrlRequest: URLRequest(url: WebUri(_initialUrl)),
            initialSettings: InAppWebViewSettings(
              javaScriptEnabled: true,
              useShouldOverrideUrlLoading: true,
              useOnDownloadStart: true,
              supportZoom: false,
              builtInZoomControls: false,
            ),
            initialUserScripts: UnmodifiableListView<UserScript>([
              UserScript(
                source: '''
                  window.appInterface = {
                    postMessage: function(message) {
                      if (window.flutter_inappwebview && window.flutter_inappwebview.callHandler) {
                        window.flutter_inappwebview.callHandler('appInterface', message);
                      } else {
                        window.__traccarMessageQueue = window.__traccarMessageQueue || [];
                        window.__traccarMessageQueue.push(message);
                      }
                    }
                  };
                  (function() {
                    if (window.__dhfvDownloads) return;
                    window.__dhfvDownloads = true;
                    var blobs = new Map();
                    var originalCreateObjectURL = URL.createObjectURL;
                    URL.createObjectURL = function(object) {
                      var url = originalCreateObjectURL.apply(this, arguments);
                      if (object instanceof Blob) blobs.set(url, object);
                      return url;
                    };
                    var clean = function(value) { return String(value || '').replace(/[|\\r\\n]/g, '_'); };
                    var post = function(message) { window.appInterface.postMessage(message); };
                    var sendBlob = function(blob, name) {
                      var reader = new FileReader();
                      reader.onload = function() {
                        post('download|' + clean(blob.type || 'application/octet-stream') + '|' + clean(name || 'download')
                          + '|' + String(reader.result).split(',')[1]);
                      };
                      reader.readAsDataURL(blob);
                    };
                    // blob: and data: files exist only inside the page, so read them here.
                    var handleInPage = function(href, name) {
                      if (href.indexOf('blob:') === 0) {
                        var blob = blobs.get(href);
                        if (blob) { sendBlob(blob, name); return true; }
                        fetch(href).then(function(r) { return r.blob(); }).then(function(b) { sendBlob(b, name); });
                        return true;
                      }
                      if (href.indexOf('data:') === 0) {
                        var match = /^data:([^;,]*)((?:;[^;,]*)*?)(;base64)?,([\\s\\S]*)\$/.exec(href);
                        if (!match) return false;
                        var b64 = match[3] ? match[4] : btoa(unescape(encodeURIComponent(decodeURIComponent(match[4]))));
                        post('download|' + clean(match[1] || 'application/octet-stream') + '|' + clean(name || 'download') + '|' + b64);
                        return true;
                      }
                      return false;
                    };
                    var handleAnchor = function(anchor) {
                      var href = anchor.href || '';
                      var name = anchor.getAttribute('download');
                      if (href.indexOf('blob:') === 0 || href.indexOf('data:') === 0) return handleInPage(href, name);
                      if (name !== null && /^https?:/.test(href)) { post('downloadUrl|' + clean(name) + '|' + href); return true; }
                      return false;
                    };
                    document.addEventListener('click', function(event) {
                      var anchor = event.target && event.target.closest ? event.target.closest('a[href]') : null;
                      if (anchor && handleAnchor(anchor)) { event.preventDefault(); event.stopImmediatePropagation(); }
                    }, true);
                    // Code-triggered downloads (e.g. file-saver) click links that aren't in the page.
                    var originalClick = HTMLAnchorElement.prototype.click;
                    HTMLAnchorElement.prototype.click = function() {
                      if (handleAnchor(this)) return;
                      return originalClick.apply(this, arguments);
                    };
                    var originalDispatch = EventTarget.prototype.dispatchEvent;
                    EventTarget.prototype.dispatchEvent = function(event) {
                      if (event && event.type === 'click' && this instanceof HTMLAnchorElement && !this.isConnected && handleAnchor(this)) {
                        return false;
                      }
                      return originalDispatch.apply(this, arguments);
                    };
                    var originalOpen = window.open;
                    window.open = function(url) {
                      if (typeof url === 'string' && (url.indexOf('blob:') === 0 || url.indexOf('data:') === 0) && handleInPage(url, 'download')) {
                        return null;
                      }
                      return originalOpen.apply(this, arguments);
                    };
                  })();
                  window.addEventListener('flutterInAppWebViewPlatformReady', function() {
                    if (window.__traccarMessageQueue && window.flutter_inappwebview && window.flutter_inappwebview.callHandler) {
                      window.__traccarMessageQueue.forEach(function(message) {
                        window.flutter_inappwebview.callHandler('appInterface', message);
                      });
                      window.__traccarMessageQueue = [];
                    }
                  });
                ''',
                injectionTime: UserScriptInjectionTime.AT_DOCUMENT_START,
              ),
            ]),
            onWebViewCreated: (controller) {
              _controller = controller;
              controller.addJavaScriptHandler(
                handlerName: 'appInterface',
                callback: (args) {
                  if (args.isEmpty) return null;
                  _handleWebMessage(args.first.toString());
                  return null;
                },
              );
              _controllerReady = true;
              _maybeCompleteInitialized();
            },
            onLoadStart: (controller, url) {
              setState(() => _loadingError = null);
            },
            shouldOverrideUrlLoading: (controller, navigationAction) async {
              final target = navigationAction.request.url;
              if (target == null) {
                return NavigationActionPolicy.ALLOW;
              }
              final uri = Uri.parse(target.toString());
              if (uri.scheme == 'blob' || uri.scheme == 'data') {
                // Handled by the injected page script; never navigate to them.
                return NavigationActionPolicy.CANCEL;
              }
              if (['response_type', 'client_id', 'redirect_uri', 'scope'].every(uri.queryParameters.containsKey)) {
                _launchAuthorizeRequest(uri);
                return NavigationActionPolicy.CANCEL;
              }
              if (uri.authority != Uri.parse(_getUrl()).authority) {
                try {
                  launchUrl(uri, mode: LaunchMode.externalApplication);
                } catch (e) {
                  developer.log('Failed to launch url', error: e);
                }
                return NavigationActionPolicy.CANCEL;
              }
              if (_isDownloadable(uri)) {
                await _downloadFile(uri);
                return NavigationActionPolicy.CANCEL;
              }
              return NavigationActionPolicy.ALLOW;
            },
            onDownloadStartRequest: (controller, request) async {
              final uri = Uri.parse(request.url.toString());
              await _downloadFile(
                uri,
                suggestedFileName: request.suggestedFilename,
                mimeType: request.mimeType,
              );
            },
            onReceivedError: (controller, request, error) {
              if (request.isForMainFrame == true) {
                final isInterruptedFrameLoad = Platform.isIOS && error.description.contains('code=102');
                if (error.type == WebResourceErrorType.CANCELLED || isInterruptedFrameLoad) {
                  return;
                }
                final errorMessage = error.description.isNotEmpty
                  ? error.description
                  : error.type.toString();
                setState(() => _loadingError = errorMessage);
              }
            },
            onRenderProcessGone: (controller, detail) async {
              await controller.reload();
            },
            onWebContentProcessDidTerminate: (controller) {
              controller.reload();
            },
            onGeolocationPermissionsShowPrompt: (controller, origin) async {
              final status = await Permission.location.request();
              return GeolocationPermissionShowPromptResponse(
                origin: origin,
                allow: status.isGranted,
                retain: true,
              );
            },
            onPermissionRequest: (controller, request) async {
              var allGranted = true;
              for (final resource in request.resources) {
                PermissionStatus status;
                final resourceUpper = resource.toString().toUpperCase();
                if (resourceUpper.contains('VIDEO_CAPTURE') || resourceUpper.contains('CAMERA')) {
                  status = await Permission.camera.request();
                } else {
                  allGranted = false;
                  continue;
                }
                if (!status.isGranted) allGranted = false;
              }
              return PermissionResponse(
                resources: request.resources,
                action: allGranted
                  ? PermissionResponseAction.GRANT
                  : PermissionResponseAction.DENY,
              );
            },
          ),
        ),
      ),
    );
  }
}
