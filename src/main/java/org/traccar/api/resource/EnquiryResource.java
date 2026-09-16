/*
 * Copyright 2026 ${title} contributors
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 */
package org.traccar.api.resource;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.traccar.mail.MailManager;
import org.traccar.model.User;

import jakarta.annotation.security.PermitAll;
import jakarta.inject.Inject;
import jakarta.ws.rs.Consumes;
import jakarta.ws.rs.POST;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.Produces;
import jakarta.ws.rs.core.MediaType;
import jakarta.ws.rs.core.Response;

import java.util.Map;

/**
 * Public sales-enquiry endpoint. Collects a prospect's name, email and phone and
 * dispatches an enquiry to the ${title} team. Uses the server's MailManager,
 * which logs the message when SMTP is not yet configured.
 */
@Path("enquiry")
@Produces(MediaType.APPLICATION_JSON)
@Consumes(MediaType.APPLICATION_JSON)
public class EnquiryResource {

    private static final Logger LOGGER = LoggerFactory.getLogger(EnquiryResource.class);
    private static final String RECIPIENT = "admin@${serverHost}";

    @Inject
    private MailManager mailManager;

    @POST
    @PermitAll
    public Response submit(Map<String, String> body) {
        String name = body.getOrDefault("name", "").trim();
        String email = body.getOrDefault("email", "").trim();
        String phone = body.getOrDefault("phone", "").trim();

        if (name.isEmpty() || email.isEmpty() || phone.isEmpty()) {
            return Response.status(Response.Status.BAD_REQUEST)
                    .entity(Map.of("error", "Name, email and phone are required"))
                    .build();
        }

        String subject = "New ${title} enquiry from " + name;
        String text = "A new sales enquiry has been received.\n\n"
                + "Name:  " + name + "\n"
                + "Email: " + email + "\n"
                + "Phone: " + phone + "\n";

        LOGGER.info("Enquiry received: name={}, email={}, phone={}", name, email, phone);

        try {
            User recipient = new User();
            recipient.setName("${title} Team");
            recipient.setEmail(RECIPIENT);
            mailManager.sendMessage(recipient, true, subject, text);
        } catch (Exception e) {
            // The enquiry is already captured in the log above; delivery is best-effort.
            LOGGER.warn("Enquiry email dispatch failed (captured in log only): {}", e.getMessage());
        }

        return Response.ok(Map.of("status", "received")).build();
    }
}
