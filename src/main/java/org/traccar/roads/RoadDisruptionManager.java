/*
 * Copyright (c) 2026 Infomac Solutions. All rights reserved.
 * Proprietary and confidential. No licence is granted by access to this file.
 * See LICENSE in the repository root.
 */
/*
 * Copyright 2026 DH FleetView contributors
 */
package org.traccar.roads;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.traccar.config.Config;
import org.traccar.config.Keys;

import jakarta.inject.Inject;
import jakarta.inject.Singleton;
import javax.xml.stream.XMLInputFactory;
import javax.xml.stream.XMLStreamConstants;
import javax.xml.stream.XMLStreamReader;

import java.io.InputStream;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.time.Instant;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Deque;
import java.util.List;
import java.util.Locale;

/**
 * Live disruption on the strategic road network, from National Highways.
 *
 * Their DATEX II feed is one 11 MB document of every closure they know about -
 * about 500 records, of which only the active ones are happening now. It is
 * read with a streaming parser rather than a DOM so the whole document never
 * sits in memory, and the result is cached: the feed changes slowly, the map
 * may have many viewers, and their rate limit is 10 calls a minute.
 *
 * Feed: https://api.data.nationalhighways.co.uk/roads/v2.0/closures
 * Needs a free subscription key (`roads.nationalHighwaysKey`).
 */
@Singleton
public class RoadDisruptionManager {

    private static final Logger LOG = LoggerFactory.getLogger(RoadDisruptionManager.class);

    private static final String FEED_URL =
            "https://api.data.nationalhighways.co.uk/roads/v2.0/closures";
    private static final Duration FETCH_TIMEOUT = Duration.ofSeconds(90);

    private final Config config;
    private final HttpClient client = HttpClient.newBuilder()
            .connectTimeout(Duration.ofSeconds(15))
            .followRedirects(HttpClient.Redirect.NORMAL)
            .build();

    private volatile List<Disruption> cached = List.of();
    private volatile Instant fetchedAt = Instant.EPOCH;
    private volatile String lastError;

    @Inject
    public RoadDisruptionManager(Config config) {
        this.config = config;
    }

    public boolean isConfigured() {
        String key = config.getString(Keys.ROADS_NATIONAL_HIGHWAYS_KEY);
        return key != null && !key.isBlank();
    }

    public String getLastError() {
        return lastError;
    }

    public Instant getFetchedAt() {
        return fetchedAt;
    }

    /**
     * Everything currently on the network, refreshed no more often than the
     * cache interval. Callers get the cached copy while it is fresh; a failed
     * refresh keeps the last good answer rather than emptying the map.
     */
    public synchronized List<Disruption> getDisruptions() {
        long minutes = config.getInteger(Keys.ROADS_REFRESH_MINUTES, 5);
        if (Instant.now().isBefore(fetchedAt.plus(Duration.ofMinutes(minutes))) && !cached.isEmpty()) {
            return cached;
        }
        if (!isConfigured()) {
            lastError = "No National Highways subscription key configured (roads.nationalHighwaysKey).";
            return List.of();
        }
        try {
            HttpRequest request = HttpRequest.newBuilder(URI.create(FEED_URL))
                    .timeout(FETCH_TIMEOUT)
                    .header("Ocp-Apim-Subscription-Key", config.getString(Keys.ROADS_NATIONAL_HIGHWAYS_KEY))
                    .GET()
                    .build();
            HttpResponse<InputStream> response = client.send(
                    request, HttpResponse.BodyHandlers.ofInputStream());
            if (response.statusCode() != 200) {
                lastError = "National Highways answered " + response.statusCode();
                LOG.warn("Road disruption feed: {}", lastError);
                return cached;
            }
            try (InputStream stream = response.body()) {
                List<Disruption> parsed = parse(stream);
                cached = parsed;
                fetchedAt = Instant.now();
                lastError = null;
                LOG.info("Road disruption feed: {} records, {} active", parsed.size(),
                        parsed.stream().filter(Disruption::isActive).count());
            }
        } catch (Exception e) {
            lastError = e.getClass().getSimpleName() + ": " + e.getMessage();
            LOG.warn("Road disruption feed failed: {}", lastError);
        }
        return cached;
    }

    /**
     * Parse the DATEX II payload into the few fields a transport office needs.
     *
     * Streaming, and deliberately tolerant: the schema nests the same element
     * names at several depths, so values are taken from the nearest enclosing
     * element that gives them meaning rather than by absolute path. An element
     * nobody recognises is skipped, not fatal - this feed is not ours and will
     * change without telling us.
     */
    private List<Disruption> parse(InputStream stream) throws Exception {
        XMLInputFactory factory = XMLInputFactory.newInstance();
        factory.setProperty(XMLInputFactory.IS_SUPPORTING_EXTERNAL_ENTITIES, false);
        factory.setProperty(XMLInputFactory.SUPPORT_DTD, false);
        XMLStreamReader reader = factory.createXMLStreamReader(stream);

        List<Disruption> out = new ArrayList<>();
        Deque<String> path = new ArrayDeque<>();
        Disruption current = null;
        String text = null;
        boolean firstPosition = true;

        while (reader.hasNext()) {
            int event = reader.next();
            if (event == XMLStreamConstants.START_ELEMENT) {
                String name = reader.getLocalName();
                path.push(name);
                if ("situationRecord".equals(name)) {
                    current = new Disruption();
                    firstPosition = true;
                }
                text = null;
            } else if (event == XMLStreamConstants.CHARACTERS || event == XMLStreamConstants.CDATA) {
                String chunk = reader.getText();
                text = text == null ? chunk : text + chunk;
            } else if (event == XMLStreamConstants.END_ELEMENT) {
                String name = path.isEmpty() ? reader.getLocalName() : path.pop();
                String value = text == null ? null : text.trim();
                text = null;
                if (current == null) {
                    continue;
                }
                if (value != null && !value.isEmpty()) {
                    switch (name) {
                        case "idG" -> {
                            if (current.id == null) {
                                current.id = value;
                            }
                        }
                        case "validityStatus" -> current.status = value;
                        case "overallStartTime" -> current.start = value;
                        case "overallEndTime" -> current.end = value;
                        case "causeType" -> current.cause = value;
                        case "comment" -> {
                            if (current.description == null) {
                                current.description = value;
                            }
                        }
                        case "locationDescription" -> {
                            if (current.where == null) {
                                current.where = value;
                            }
                        }
                        case "lanesStatus" -> current.lanes = value;
                        case "posList" -> {
                            if (firstPosition) {
                                setPosition(current, value);
                                firstPosition = false;
                            }
                        }
                        default -> { }
                    }
                }
                if ("situationRecord".equals(name)) {
                    if (current.latitude != 0 || current.longitude != 0) {
                        current.road = roadFrom(current.where, current.description);
                        out.add(current);
                    }
                    current = null;
                }
            }
        }
        reader.close();
        return out;
    }

    /** The first coordinate pair of the line, which is where the disruption starts. */
    private void setPosition(Disruption disruption, String posList) {
        String[] parts = posList.trim().split("\\s+");
        if (parts.length >= 2) {
            try {
                disruption.latitude = Double.parseDouble(parts[0]);
                disruption.longitude = Double.parseDouble(parts[1]);
            } catch (NumberFormatException e) {
                LOG.debug("unreadable position: {}", posList);
            }
        }
    }

    /**
     * The road number, pulled out of the text because the feed gives it nowhere
     * structured. "A14 eastbound between J25 and J31" is what an operator reads
     * first, and it is what a vehicle's own road has to be matched against.
     */
    private String roadFrom(String where, String description) {
        for (String source : new String[] {where, description}) {
            if (source == null) {
                continue;
            }
            var matcher = java.util.regex.Pattern
                    .compile("\\b([AM]\\d{1,4}(?:\\(M\\))?)\\b").matcher(source.toUpperCase(Locale.UK));
            if (matcher.find()) {
                return matcher.group(1);
            }
        }
        return null;
    }

    /** One disruption, flattened to what gets shown. */
    public static final class Disruption {
        private String id;
        private String status;
        private String cause;
        private String description;
        private String where;
        private String road;
        private String lanes;
        private String start;
        private String end;
        private double latitude;
        private double longitude;

        public String getId() {
            return id;
        }

        public String getStatus() {
            return status;
        }

        public String getCause() {
            return cause;
        }

        public String getDescription() {
            return description;
        }

        public String getWhere() {
            return where;
        }

        public String getRoad() {
            return road;
        }

        public String getLanes() {
            return lanes;
        }

        public String getStart() {
            return start;
        }

        public String getEnd() {
            return end;
        }

        public double getLatitude() {
            return latitude;
        }

        public double getLongitude() {
            return longitude;
        }

        public boolean isActive() {
            return "active".equals(status);
        }
    }
}
