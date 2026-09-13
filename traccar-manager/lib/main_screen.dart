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

  bool _isDownloadable(Uri uri) {
    final path = uri.path.toLowerCase();
    final lastSegment = uri.pathSegments.isNotEmpty ? uri.pathSegments.last.toLowerCase() : '';
    final extension = lastSegment.contains('.') ? lastSegment.split('.').last : '';
    final downloadQuery = uri.queryParameters['download'] == 'true'
        || uri.queryParameters['format'] != null && ['csv', 'gpx', 'kml', 'kmz', 'xlsx', 'pdf'].contains(uri.queryParameters['format']!.toLowerCase());
    return ['xlsx', 'kml', 'kmz', 'csv', 'gpx', 'pdf', 'exe', 'ddd'].contains(extension)
        || lastSegment == 'download'
        || downloadQuery
        || path.contains('/export/');
  }

  String _safeFileName(String value) {
    final cleaned = value.replaceAll(RegExp(r'[^A-Za-z0-9._-]'), '_');
    return cleaned.isEmpty ? 'download' : cleaned;
  }

  String _extensionForMime(String? mimeType) {
    switch (mimeType?.toLowerCase()) {
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
      case 'application/octet-stream':
        return 'bin';
      default:
        return 'download';
    }
  }

  Future<void> _saveDownloadedBytes(
    Uint8List bytes, {
    String? fileName,
    String? mimeType,
  }) async {
    final name = _safeFileName(fileName ?? '${DateTime.now().millisecondsSinceEpoch}.${_extensionForMime(mimeType)}');
    await _shareFile(name, bytes);
  }

  Future<void> _downloadFile(
    Uri uri, {
    String? suggestedFileName,
    String? mimeType,
  }) async {
    try {
      final token = await _loginTokenStore.read(false);
      if (token == null) return;
      final response = await http.get(uri, headers: {'Authorization': 'Bearer $token'});
      if (response.statusCode == 200) {
        final disposition = response.headers['content-disposition'] ?? '';
        final match = RegExp(r'''filename\*?=(?:UTF-8''|utf-8'')?"?([^";]+)"?''').firstMatch(disposition);
        final headerFileName = match?.group(1);
        final fileName = headerFileName != null && headerFileName.isNotEmpty
            ? Uri.decodeComponent(headerFileName)
            : suggestedFileName;
        await _saveDownloadedBytes(
          response.bodyBytes,
          fileName: fileName,
          mimeType: mimeType ?? response.headers['content-type'],
        );
      } else {
        developer.log('Failed file download request: ${response.statusCode}');
      }
    } catch (e) {
      developer.log('Failed to download file', error: e);
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
        try {
          if (parts.length >= 4) {
            await _saveDownloadedBytes(
              base64Decode(parts[3]),
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
            'DH FleetView',
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
                  const originalCreateObjectURL = URL.createObjectURL;
                  const downloadableBlobs = new Map();
                  URL.createObjectURL = function(object) {
                    const url = originalCreateObjectURL.apply(this, arguments);
                    if (object instanceof Blob) {
                      downloadableBlobs.set(url, object);
                    }
                    return url;
                  };
                  document.addEventListener('click', function(event) {
                    const anchor = event.target && event.target.closest
                      ? event.target.closest('a[download]')
                      : null;
                    if (!anchor) return;
                    const blob = downloadableBlobs.get(anchor.href);
                    if (!blob) return;
                    event.preventDefault();
                    event.stopPropagation();
                    const reader = new FileReader();
                    reader.onload = () => {
                      const encodedName = (anchor.download || 'download').replace(/\|/g, '_');
                      window.appInterface.postMessage(
                        'download|' + (blob.type || 'application/octet-stream')
                        + '|' + encodedName + '|' + reader.result.split(',')[1],
                      );
                    };
                    reader.readAsDataURL(blob);
                  }, true);
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
